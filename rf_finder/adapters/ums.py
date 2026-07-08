"""UMS (United Monolithic Semiconductors, ums-rf.com) amplifier adapter.

Plan: specs/rf-component-finder/iteration2/ums-plan.md.

Fetch strategy: UMS is a WordPress site whose Product Finder is a pure URL-driven
form.  The plain ``/products/`` page renders a "catalog" view with NO spec
columns (Reference/Description/Case only); adding a ``?function=<slug>`` query
switches it to the "archive-product" template, which server-side renders a full
parametric table (Gain, NF, P1dB, IP3, Psat, RF Bandwidth, Bias…) as real
``<td>`` cells.  So we issue ONE GET per amplifier sub-type (LNA, HPA, MPA,
Analog VGA, Digital VGA) — 5 requests cover every amplifier (~156).  Plain
``httpx``; no JavaScript, no Playwright, no per-product fetches (ums-plan §1, §4).

The frequency/power sliders filter client-side only and are broken server-side
(a narrowed range returns 0 rows), so we always send the full default range and
let the Verifier apply every constraint (ums-plan §0, R3) — same return-all
contract as the Mini-Circuits and MACOM adapters (REQ-4.1).

Per-category column sets differ (IP3/Psat on power types; NF on low-noise/VGA
types), so columns are mapped by their ``<thead>`` label, never by position
(ums-plan §5).  Spec ``<th>`` cells carry nested sort-caret markup, so header
text is read with selectolax (nested-tolerant), not a flat regex.

robots.txt note: only ``/wp-admin/`` is disallowed; ``/products/`` is allowed and
there is no ``Crawl-delay``.  We self-impose a modest delay between the 5 live
GETs and serve repeats from cache (ums-plan §2, §8).
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from rf_finder import cache
from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.ums-rf.com"
_PRODUCTS_URL = _BASE_URL + "/products/"

# The amplifier sub-type slugs (from the embedded umsFilterData.product_types).
# One GET per slug; together they cover every amplifier (ums-plan §0, §6).
_AMPLIFIER_SLUGS = (
    "amplifier-lna",
    "amplifier-hpa",
    "amplifier-mpa",
    "amplifier-analogvga",
    "amplifier-digitalvga",
)

# Full default frequency/power range.  Narrowing these returns 0 rows (the
# server-side numeric filter is broken — ums-plan §0/R3), so always send the
# full range and let the Verifier filter.
_RANGE_PARAMS = {
    "frequency-min": "0",
    "frequency-max": "105.5",
    "power-min": "0",
    "power-max": "200",
    "power-unit": "watt",
}

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "—"})

# ---------------------------------------------------------------------------
# Column mapping: normalised <thead> label -> (canonical_name, unit).
# RF Bandwidth (Min)/(Max) are handled specially (combined into freq_range).
# Every other column (Bias mA, Gain Control Range, Gain Flatness, Dynamic
# Range, Case) is skipped — not in the amplifier ontology (ums-plan §5).
# ---------------------------------------------------------------------------

COLUMN_MAP: dict[str, tuple[str, str]] = {
    "gain db":               ("Gain", "dB"),
    "noise figure db":       ("NF",   "dB"),
    "p 1db out dbm":         ("P1dB", "dBm"),
    "ip3 dbm":               ("IP3",  "dBm"),
    "sat output power dbm":  ("Psat", "dBm"),
    "bias v":                ("VDD",  "V"),
}

_FREQ_MIN_HDR = "rf bandwidth ghz min"
_FREQ_MAX_HDR = "rf bandwidth ghz max"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_header(raw: str) -> str:
    """Lowercase, drop punctuation (parens, +/-, slashes, dots), collapse space.

    Folds e.g. ``"P-1dB OUT (dBm)"`` -> ``"p 1db out dbm"`` and
    ``"RF Bandwidth (GHz) (Min)"`` -> ``"rf bandwidth ghz min"`` so the map keys
    stay readable and robust to punctuation drift.
    """
    text = raw.lower()
    text = re.sub(r"[()+/\\.,:±-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(cell_text: str) -> float | None:
    """Return float for numeric cells; None for empty / '-' / non-numeric.

    A None result means the param is simply omitted from raw_params, so the
    Verifier marks a requested-but-missing spec UNKNOWN (partial), never FAIL.
    """
    t = cell_text.strip()
    if t in _MISSING_SENTINELS or not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class UmsAdapter(Adapter):
    """Scrapes ums-rf.com ``?function=<slug>`` parametric tables for amplifiers."""

    manufacturer = "UMS"
    supported_components = {"amplifier"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch every amplifier sub-type table and return all rows as Candidates.

        No server-side numeric filtering is applied (the UMS sliders are broken
        server-side); the Verifier applies all constraints (REQ-4.1).
        """
        candidates: list[Candidate] = []
        for slug in _AMPLIFIER_SLUGS:
            html = self._fetch_category(slug)
            candidates.extend(self._parse_html(html))
        return candidates

    def _fetch_category(self, slug: str) -> str:
        """GET one ``?function=<slug>`` parametric page (cache-first).

        The query params feed the cache key, so each slug is a distinct file. The
        shared provider owns the User-Agent, the 3 s delay, the timeout and
        retries. Raises ``AdapterError`` when a page is unreachable with no
        cached copy.
        """
        result = cache.fetch(
            self.manufacturer,
            _PRODUCTS_URL,
            params={"function": slug, **_RANGE_PARAMS},
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if result.text is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error fetching products for function={slug}",
            )
        return result.text

    # ------------------------------------------------------------------
    # Internal parse method (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse one category page; return a Candidate per product row.

        Raises AdapterError if no parametric product table is found (catalog
        view, site redesign, or an empty/blocked response) — fail loudly rather
        than silently returning nothing.
        """
        tree = HTMLParser(html)

        # The parametric table is the one carrying product rows.  Locate it via
        # a row, then climb to its <table>; this is robust to the exact table
        # class/id (the page has unrelated tables too).
        first_row = tree.css_first("tr.product-row")
        table = None
        if first_row is not None:
            node = first_row.parent
            while node is not None and node.tag != "table":
                node = node.parent
            table = node
        if table is None:
            table = tree.css_first("table.product-table")
        if table is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="no parametric product table found in HTML",
            )

        # ---- Header labels (nested-tolerant: spec <th> contain sort carets) --
        header_texts: list[str] = []
        thead = table.css_first("thead")
        if thead is not None:
            for tr in thead.css("tr"):
                ths = tr.css("th")
                if ths:
                    header_texts = [th.text(strip=True) for th in ths]
                    break
        if not header_texts:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="parametric table has no <thead> column labels",
            )

        # characteristic-cell columns correspond to headers AFTER the first two
        # (Reference, Description); map normalised label -> offset into the
        # row's characteristic-cell list (ums-plan §4).
        char_headers = [_normalize_header(h) for h in header_texts[2:]]
        col_index: dict[str, int] = {}
        for idx, norm in enumerate(char_headers):
            if norm and norm not in col_index:
                col_index[norm] = idx

        # ---- Data rows -------------------------------------------------------
        candidates: list[Candidate] = []
        for row in table.css("tr.product-row"):
            candidate = self._build_candidate(row, col_index)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # ------------------------------------------------------------------
    # Candidate construction
    # ------------------------------------------------------------------

    def _build_candidate(
        self, row, col_index: dict[str, int]  # noqa: ANN001 (selectolax Node)
    ) -> Candidate | None:
        """Build one Candidate from a ``<tr class="product-row">``; None if no model."""
        link = row.css_first("a.product-link")
        model = link.text(strip=True) if link is not None else ""
        if not model:
            return None

        href = link.attributes.get("href", "") if link is not None else ""
        if href:
            url = href if href.startswith("http") else _BASE_URL + "/" + href.lstrip("/")
        else:
            url = f"{_PRODUCTS_URL}{model.lower()}/"

        cell_texts = [c.text(strip=True) for c in row.css("td.characteristic-cell")]

        def _val(norm_key: str) -> str:
            idx = col_index.get(norm_key)
            if idx is None or idx >= len(cell_texts):
                return "-"
            return cell_texts[idx]

        raw_params: dict[str, RawValue] = {}

        # Frequency range: combine RF Bandwidth (Min) + (Max), already GHz.
        f_low = _parse_float(_val(_FREQ_MIN_HDR))
        f_high = _parse_float(_val(_FREQ_MAX_HDR))
        if f_low is not None and f_high is not None:
            raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="GHz")

        # Scalar params from COLUMN_MAP.
        for norm_key, (canonical, unit) in COLUMN_MAP.items():
            value = _parse_float(_val(norm_key))
            if value is not None:
                raw_params[canonical] = RawValue(value=value, unit=unit)

        return Candidate(
            model=model,
            manufacturer=self.manufacturer,
            url=url,
            raw_params=raw_params,
            source="table",
        )
