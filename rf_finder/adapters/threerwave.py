"""3rWave (3rwave.com) amplifier adapter.

Fetch strategy: a single HTTP GET to /amplifier/.  The page is a WordPress site
whose product specs are rendered by the **TablePress** plugin: the full PA
(power amplifier) and LNA (low-noise amplifier) tables are server-side rendered
as real ``<td class="column-N">`` cells in the initial HTML.  DataTables.js only
adds client-side paging/search/sort on top — no AJAX, no POST, no JavaScript
rendering is required to read the data (same family as the Mini-Circuits and UMS
adapters; contrast the embedded-JSON MACOM / Analog Devices adapters).

PA and LNA are two amplifier sub-types on one page; both map to component type
``amplifier``.  This adapter parses every ``table.tablepress`` on the page and
returns ALL rows; the Verifier applies all constraints (REQ-4.1).

Frequency is already in GHz on the site (Start Freq. / Stop Freq.) — no MHz
conversion (unlike Mini-Circuits / Analog Devices).

robots.txt note: 3rwave.com disallows nothing, so /amplifier/ is crawlable.

Deferred (see threerwave-plan.md):
  * Size — the column is free text with mixed units (mm, inch ", package-only
    strings).  How the *user's* Size input is decoded is undecided (OQ-3W-1), so
    Size is NOT emitted yet; a clearly-marked hook is left in _build_candidate.
  * P1dB, IP3, MSL, Temperature — no table columns; sourced from the per-part
    datasheet in a future iteration → resolve to UNKNOWN for now.

Runtime note (OQ-3W-10): some networks (e.g. the Etrog/safepage content filter)
intercept 3rwave.com for non-browser requests; the live fetch then fails and is
surfaced as AdapterError.  Offline parsing/tests are unaffected.
"""

from __future__ import annotations

import math
import re
from urllib.parse import quote

from selectolax.parser import HTMLParser

from rf_finder import cache
from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://3rwave.com"
_AMPLIFIER_URL = _BASE_URL + "/amplifier/"

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "NA", "—"})

# Markers of a content-filter block stub returned instead of the real page
# (e.g. the Etrog/safepage filter — see threerwave-plan.md OQ-3W-10).  Detected
# so the failure is legible instead of a confusing "no table" error.
_BLOCK_MARKERS = ("safepage.etrog", "block/block1", "cause=url_level")

# ---------------------------------------------------------------------------
# Column mapping: normalised header text -> (canonical_name, unit | None)
# "model", "freq_low", "freq_high" are handled specially; all others map to
# raw_params.  Headers not in this dict (Consumption Current, Efficiency, Size,
# Connector, Description) are skipped.
# ---------------------------------------------------------------------------

COLUMN_MAP: dict[str, tuple[str, str | None]] = {
    "part number":     ("model",     None),
    "start freq ghz":  ("freq_low",  "GHz"),
    "stop freq ghz":   ("freq_high", "GHz"),
    "gain db":         ("Gain",      "dB"),
    "psat dbm":        ("Psat",      "dBm"),
    "nf db":           ("NF",        "dB"),
    "drain voltage v": ("VDD",       "V"),
}

# Normalised header that identifies the real header row of a product table.
_MODEL_HEADER = "part number"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_header(raw: str) -> str:
    """Lowercase, replace every non-alphanumeric run with a space, trim.

    Reducing *any* punctuation or symbol (not just a fixed set) to whitespace
    keeps header matching robust to DataTables sort carets and other glyphs the
    live site may inject, e.g. "Gain(dB) ▲" -> "gain db", "Start Freq.(GHz)" ->
    "start freq ghz".  Only [a-z0-9] and single spaces survive.
    """
    text = re.sub(r"[^a-z0-9]+", " ", raw.lower())
    return text.strip()


_LEADING_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def _parse_float(cell_text: str) -> float | None:
    """Return the numeric value of a spec cell, or None if it carries no number.

    Missing sentinels ('-', 'N/A', blank, …) and non-numeric text ('TBD',
    'Die') return None so the Verifier resolves them to UNKNOWN (a partial
    match, never a wrong FAIL).

    Beyond a clean number the parser also tolerates:
      * thousands separators — "1,500" -> 1500.0;
      * a trailing qualifier — "30 typ", "1.2 max" -> 30.0 / 1.2 (first token);
    and rejects non-finite results — "nan"/"inf" -> None.

    Caveat: an in-cell range like "28-32" yields its first number (28.0).  The
    3rwave columns we read are single-valued, so this is not expected to fire.
    """
    t = cell_text.strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    t = t.replace(",", "")
    try:
        val = float(t)
    except ValueError:
        match = _LEADING_NUMBER_RE.search(t)
        if match is None:
            return None
        try:
            val = float(match.group())
        except ValueError:
            return None
    return val if math.isfinite(val) else None


def _highlight_url(part_number: str) -> str:
    """Build a Scroll-to-Text-Fragment deep link into the shared amplifier page.

    3rwave has no per-part page or datasheet (OQ-3W-6), so a bare ``/amplifier/``
    link can't tell the user *which* of the 40+ rows a result refers to.  A text
    fragment directive (``#:~:text=<part number>``) makes Chrome/Edge and other
    modern browsers scroll to and highlight that exact Part Number on the table
    page — the same highlight a manual Ctrl+F produces.  Browsers without the
    feature (e.g. older Firefox) simply ignore the fragment and load the page.

    The part number is percent-encoded; ``-`` is force-encoded to ``%2D`` because
    a literal ``-`` is the range delimiter in the text-fragment grammar.
    """
    encoded = quote(part_number, safe="").replace("-", "%2D")
    return f"{_AMPLIFIER_URL}#:~:text={encoded}"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class ThreeRWaveAdapter(Adapter):
    """Scrapes 3rwave.com /amplifier/ (PA + LNA TablePress tables)."""

    manufacturer = "3rWave"
    supported_components = {"amplifier"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the amplifier page (cache-first); return every PA + LNA row.

        No server-side filtering exists (DataTables filters client-side only);
        all rows are returned and the Verifier applies all constraints. The
        shared provider owns the User-Agent, delay, timeout and retries; a
        ``None`` body means unreachable with no cached copy → skip this source.
        """
        result = cache.fetch(
            self.manufacturer,
            _AMPLIFIER_URL,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        if result.text is None:
            return []

        return self._parse_html(result.text)

    # ------------------------------------------------------------------
    # Internal parse method (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse HTML string; return list of Candidates from all product tables.

        Raises AdapterError if the response is a content-filter block stub, or
        if no ``table.tablepress`` is found in the HTML — the site-redesign
        tripwire (fail loudly, never return empty silently).
        """
        # A network content filter may return a short block stub (HTTP 200)
        # instead of the real page; distinguish it from a genuine redesign.
        if any(marker in html for marker in _BLOCK_MARKERS):
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=(
                    "request intercepted by a content filter (e.g. Etrog/"
                    "safepage) — whitelist 3rwave.com to fetch live"
                ),
            )

        tree = HTMLParser(html)
        tables = tree.css("table.tablepress")
        if not tables:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="no table.tablepress found in HTML",
            )

        candidates: list[Candidate] = []
        for table in tables:
            candidates.extend(self._parse_table(table))
        return candidates

    # ------------------------------------------------------------------
    # Per-table parsing
    # ------------------------------------------------------------------

    def _parse_table(self, table) -> list[Candidate]:
        """Parse one TablePress table into Candidates.

        Tables whose header row has no "Part Number" column are skipped (the
        page may carry unrelated tables); both the PA and LNA tables share the
        same header set, so one COLUMN_MAP serves both.
        """
        # ---- Locate the header row (the <tr> containing "Part Number") ----
        header_texts: list[str] = []
        thead = table.css_first("thead")
        candidate_rows = thead.css("tr") if thead else table.css("tr")
        for tr in candidate_rows:
            texts = [c.text(strip=True) for c in tr.css("th")] or [
                c.text(strip=True) for c in tr.css("td")
            ]
            if any(_normalize_header(t) == _MODEL_HEADER for t in texts):
                header_texts = texts
                break

        if not header_texts:
            return []  # not a product table

        # Build normalised-header -> column-index lookup (first occurrence wins).
        col_index: dict[str, int] = {}
        for idx, raw_header in enumerate(header_texts):
            norm = _normalize_header(raw_header)
            if norm and norm not in col_index:
                col_index[norm] = idx

        # ---- Parse data rows ----
        candidates: list[Candidate] = []
        tbody = table.css_first("tbody")
        if tbody is None:
            return candidates

        for row in tbody.css("tr"):
            cand = self._build_candidate(row, col_index)
            if cand is not None:
                candidates.append(cand)
        return candidates

    def _build_candidate(self, row, col_index: dict[str, int]) -> Candidate | None:
        """Build one Candidate from a <tr>; return None if it has no model."""
        cells = row.css("td")
        if not cells:
            return None
        cell_texts = [c.text(strip=True) for c in cells]

        def _cell_val(norm_key: str) -> str:
            idx = col_index.get(norm_key)
            if idx is None or idx >= len(cell_texts):
                return "-"
            return cell_texts[idx]

        # ---- Model (Part Number) ----
        model_idx = col_index.get(_MODEL_HEADER, 0)
        model_cell = cells[model_idx] if model_idx < len(cells) else cells[0]
        a_tag = model_cell.css_first("a")
        model_name = a_tag.text(strip=True) if a_tag else _cell_val(_MODEL_HEADER)
        if not model_name:
            return None

        # ---- Product URL (display only; never fetched) ----
        # Prefer a real per-part anchor when one exists.  When it doesn't (the
        # common 3rwave case — no per-part page/datasheet), fall back to a text-
        # fragment deep link that highlights this exact row on the shared
        # /amplifier/ page, so the link is distinguishable per component.
        href = a_tag.attributes.get("href", "") if a_tag else ""
        if href:
            url = href if href.startswith("http") else _BASE_URL + "/" + href.lstrip("/")
        else:
            url = _highlight_url(model_name)

        # ---- raw_params ----
        raw_params: dict[str, RawValue] = {}

        # Frequency range: combine Start + Stop (already GHz).
        f_low = _parse_float(_cell_val("start freq ghz"))
        f_high = _parse_float(_cell_val("stop freq ghz"))
        if f_low is not None and f_high is not None:
            raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="GHz")

        # Scalar params from COLUMN_MAP.
        for norm_key, (canonical, unit) in COLUMN_MAP.items():
            if canonical in ("model", "freq_low", "freq_high"):
                continue
            val = _parse_float(_cell_val(norm_key))
            if val is not None:
                raw_params[canonical] = RawValue(value=val, unit=unit)  # type: ignore[arg-type]

        # ---- Size hook (DEFERRED — OQ-3W-1) ----
        # The Size column is free text with mixed units (mm, inch ", package-only
        # strings) and the user-input decoding rule is undecided, so Size is NOT
        # emitted yet.  When OQ-3W-1 is resolved, parse `_cell_val("size")` here
        # (detect unit, convert inch->mm, reduce to the chosen scalar) and add it
        # to raw_params as RawValue(<scalar>, "mm").

        return Candidate(
            model=model_name,
            manufacturer=self.manufacturer,
            url=url,
            raw_params=raw_params,
            source="table",
        )
