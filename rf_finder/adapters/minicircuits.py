"""Mini-Circuits amplifier adapter (REQ-3.1, design.md §6.1–6.2, T8).

Fetch strategy: single HTTP GET to /WebStore/Amplifiers.html — the full 781-row
results table is server-side rendered in the initial response.  No AJAX, no
POST, no JavaScript rendering required (confirmed in t8-plan.md §1).

Server-side frequency filtering is NOT available: the filter inputs exist but
filtering is client-side only.  This adapter returns ALL rows; the Verifier
applies all constraints (REQ-4.1).

robots.txt note: /WebStore/Amplifiers.html is allowed.  /WebStore/modelSearch.html
is DISALLOWED and is therefore not used at all: Candidate.url is the allowed
per-model product page /WebStore/dashboard.html?model=<urlencoded> (sitemap-listed),
which is also where the datasheet link lives.

Datasheet link (case 2): the amplifiers table carries no datasheet link, so
``search()`` leaves ``datasheet_url`` as None and ``resolve_datasheet_url``
fetches the product page on demand — after Gate 1, for the handful of candidates
about to be enriched, rather than once per catalogue row.
"""

from __future__ import annotations

import re
import urllib.parse

from selectolax.parser import HTMLParser

from rf_finder import http
from rf_finder.adapters.base import Adapter, AdapterError, drop_paramless, register
from rf_finder.models import Candidate, QuerySpec, RawValue
from rf_finder.ontology.supply import parse_vdd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.minicircuits.com/WebStore/"
_AMPLIFIERS_URL = _BASE_URL + "Amplifiers.html"

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A"})

# The per-model product page: robots-allowed, sitemap-listed, and the only place
# the datasheet link is published.  The model MUST be fully percent-encoded — a
# literal "+" (which most Mini-Circuits models end with) yields HTTP 200 with no
# datasheet link at all, a silent failure.
_PRODUCT_PAGE = _BASE_URL + "dashboard.html?model={model}"

# The product page's datasheet anchor is identified by its link text.
_DATASHEET_LINK_TEXT = "datasheet"

# ---------------------------------------------------------------------------
# Column mapping: normalised header text -> (canonical_name, unit | None)
# "model", "freq_low", "freq_high" are handled specially; all others map to
# raw_params.  Headers not in this dict are skipped.
# ---------------------------------------------------------------------------

COLUMN_MAP: dict[str, tuple[str, str | None]] = {
    "model number":    ("model",     None),
    "f low mhz":       ("freq_low",  "MHz"),
    "f high mhz":      ("freq_high", "MHz"),
    "gain db typ":     ("Gain",      "dB"),
    "nf db typ":       ("NF",        "dB"),
    "p1db dbm typ":    ("P1dB",      "dBm"),
    "psat dbm typ":    ("Psat",      "dBm"),
    "oip3 dbm typ":    ("IP3",       "dBm"),
    "voltage v":       ("VDD",       "V"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_header(raw: str) -> str:
    """Lowercase, remove punctuation characters, collapse whitespace."""
    text = raw.lower()
    text = re.sub(r"[().,:/\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _product_url(model: str) -> str:
    """The robots-allowed product page for *model*, fully percent-encoded.

    ``safe=""`` is essential: nearly every Mini-Circuits model ends in "+", and
    the un-encoded form returns a 200 page carrying NO datasheet link — the
    failure is silent, so the encoding is not cosmetic.
    """
    return _PRODUCT_PAGE.format(model=urllib.parse.quote(model, safe=""))


def _parse_float(cell_text: str) -> float | None:
    """Return None for missing/non-numeric sentinels; float otherwise.

    Mini-Circuits encodes a DC-coupled lower band edge as the literal "DC"
    (i.e. 0 Hz); map it to 0.0 so DC-coupled amplifiers keep a usable
    freq_range instead of being dropped to UNKNOWN.
    """
    t = cell_text.strip()
    if t in _MISSING_SENTINELS or not t:
        return None
    if t.upper() == "DC":
        return 0.0
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class MiniCircuitsAdapter(Adapter):
    """Scrapes Mini-Circuits /WebStore/Amplifiers.html for amplifier specs."""

    manufacturer = "Mini-Circuits"
    supported_components = {"amplifier"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the full amplifiers table (cache-first) and return all rows.

        No server-side filtering is applied — the Mini-Circuits server ignores
        the freq filter form fields.  The Verifier applies all constraints. The
        shared provider owns the User-Agent, delay, timeout and retries; a
        ``None`` body means unreachable with no cached copy → skip this source.
        """
        try:
            html = self._get(_AMPLIFIERS_URL)
        except AdapterError:
            return []  # unreachable with no cached copy → skip this source

        return drop_paramless(self._parse_html(html))

    def resolve_datasheet_url(self, cand: Candidate) -> str | None:
        """Fetch the candidate's product page and return its datasheet PDF link.

        Case 2: the amplifiers table has no datasheet link, so this is the only
        way to obtain one — and it costs one request, which is why the pipeline
        calls it after Gate 1 and only for candidates it is about to enrich.

        Returns ``None`` (never raises) when the page cannot be fetched or
        carries no datasheet anchor, per the ``Adapter`` contract.
        """
        page_url = cand.url or _product_url(cand.model)
        try:
            html = self._get(page_url)
        except AdapterError:
            return None

        for a_tag in HTMLParser(html).css("a"):
            if a_tag.text(strip=True).strip().lower() != _DATASHEET_LINK_TEXT:
                continue
            href = a_tag.attributes.get("href") or ""
            if href:
                # The datasheet href is ROOT-relative ("/pdfs/<model>.pdf"), so it
                # must be joined against the host — joining it onto _BASE_URL
                # would yield /WebStore/pdfs/... and 404.
                return urllib.parse.urljoin(page_url, href)
        return None

    def _get(self, url: str) -> str:
        """GET *url* cache-first via the shared provider; raise on failure.

        The provider owns the User-Agent, delay, timeout and retries. A ``None``
        body (unreachable, no cached copy) is raised as ``AdapterError`` so the
        two callers can treat "no page" uniformly (search skips the source,
        link resolution returns ``None``).
        """
        result = http.fetch(
            self.manufacturer,
            url,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        if result.text is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"unreachable with no cached copy: {url}",
            )
        return result.text

    # ------------------------------------------------------------------
    # Internal parse method (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse HTML string; return list of Candidates.

        Raises AdapterError if ``table#maintable`` is not found in the HTML.
        """
        tree = HTMLParser(html)
        table = tree.css_first("table#maintable")
        if table is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="table#maintable not found in HTML",
            )

        # ---- Collect header cells ----------------------------------------
        # The live page has two <tr> in <thead>:
        #   Row 0: one big merged filter cell (colspan=14) -- skip
        #   Row 1: the actual column headers
        # We detect the real header row as the <tr> containing "Model Number".
        header_texts: list[str] = []

        thead = table.css_first("thead")
        if thead:
            for tr in thead.css("tr"):
                texts = [th.text(strip=True) for th in tr.css("th")]
                if any("Model Number" in t for t in texts):
                    header_texts = texts
                    break

        if not header_texts:
            # Fallback: use all <th> in the table (handles flat structures)
            header_texts = [th.text(strip=True) for th in table.css("th")]

        # Build normalised-header -> column-index lookup
        col_index: dict[str, int] = {}
        for idx, raw_header in enumerate(header_texts):
            norm = _normalize_header(raw_header)
            if norm:
                col_index[norm] = idx

        # ---- Parse data rows ----------------------------------------
        candidates: list[Candidate] = []
        tbody = table.css_first("tbody")
        if tbody is None:
            return candidates

        for row in tbody.css("tr"):
            cells = row.css("td")
            if not cells:
                continue

            # Extract text from each cell (handles <output> and plain text)
            cell_texts: list[str] = [c.text(strip=True) for c in cells]

            # Model name lives in <a> inside the first <td>
            first_td = cells[0]
            a_tag = first_td.css_first("a")
            model_name = a_tag.text(strip=True) if a_tag else cell_texts[0]

            if not model_name:
                continue

            # Product URL: the row's own <a href> is modelSearch.html, which
            # robots DISALLOWS, so it is ignored entirely.  dashboard.html is the
            # allowed product page — the one a user should land on, and the one
            # resolve_datasheet_url reads the datasheet link from.
            url = _product_url(model_name)

            # ---- Build raw_params ----------------------------------------
            raw_params: dict[str, RawValue] = {}

            def _cell_val(norm_key: str, _cell_texts: list[str] = cell_texts) -> str:
                idx = col_index.get(norm_key)
                if idx is None or idx >= len(_cell_texts):
                    return "-"
                return _cell_texts[idx]

            # Frequency range: combine F Low + F High columns
            f_low  = _parse_float(_cell_val("f low mhz"))
            f_high = _parse_float(_cell_val("f high mhz"))
            if f_low is not None and f_high is not None:
                raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="MHz")

            # VDD: the Voltage column holds a single value; the shared parser
            # normalises it to a degenerate (v, v) interval for the contains rule.
            vdd = parse_vdd(_cell_val("voltage v"))
            if vdd is not None:
                raw_params["VDD"] = RawValue(value=vdd, unit="V")

            # Scalar params from COLUMN_MAP
            for norm_key, (canonical, unit) in COLUMN_MAP.items():
                if canonical in ("model", "freq_low", "freq_high", "VDD"):
                    continue
                val = _parse_float(_cell_val(norm_key))
                if val is not None:
                    raw_params[canonical] = RawValue(value=val, unit=unit)  # type: ignore[arg-type]

            candidates.append(
                Candidate(
                    model=model_name,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params=raw_params,
                    source="table",
                )
            )

        return candidates
  