"""Mini-Circuits amplifier adapter (REQ-3.1, design.md §6.1–6.2, T8).

Fetch strategy: single HTTP GET to /WebStore/Amplifiers.html — the full 781-row
results table is server-side rendered in the initial response.  No AJAX, no
POST, no JavaScript rendering required (confirmed in t8-plan.md §1).

Server-side frequency filtering is NOT available: the filter inputs exist but
filtering is client-side only.  This adapter returns ALL rows; the Verifier
applies all constraints (REQ-4.1).

robots.txt note: /WebStore/Amplifiers.html is allowed.  /WebStore/modelSearch.html
is disallowed, so that URL is populated in Candidate.url for human reporter use
only — it is never fetched programmatically.
"""

from __future__ import annotations

import re
import time

import httpx
from selectolax.parser import HTMLParser

from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.minicircuits.com/WebStore/"
_AMPLIFIERS_URL = _BASE_URL + "Amplifiers.html"

# Browser-style User-Agent (plain bot UAs may be rejected by the CDN)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A"})

# Minimum seconds between consecutive live HTTP fetches
_MIN_DELAY_SECONDS = 1.0

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
    "psat dbm typ":    ("Pout",      "dBm"),
    "oip3 dbm typ":    ("OIP3",      "dBm"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_header(raw: str) -> str:
    """Lowercase, remove punctuation characters, collapse whitespace."""
    text = raw.lower()
    text = re.sub(r"[().,:/\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(cell_text: str) -> float | None:
    """Return None for missing/non-numeric sentinels; float otherwise."""
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
class MiniCircuitsAdapter(Adapter):
    """Scrapes Mini-Circuits /WebStore/Amplifiers.html for amplifier specs."""

    manufacturer = "Mini-Circuits"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the full amplifiers table and return all rows as Candidates.

        No server-side filtering is applied — the Mini-Circuits server ignores
        the freq filter form fields.  The Verifier applies all constraints.
        """
        # Enforce minimum inter-request delay
        elapsed = time.time() - self._last_fetch_time
        if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
            time.sleep(_MIN_DELAY_SECONDS - elapsed)

        try:
            response = httpx.get(
                _AMPLIFIERS_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.5",
                },
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()
            self._last_fetch_time = time.time()
        except httpx.HTTPError as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error fetching {_AMPLIFIERS_URL}",
                cause=exc,
            ) from exc

        return self._parse_html(response.text)

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
            model_href = a_tag.attributes.get("href", "") if a_tag else ""

            if not model_name:
                continue

            # Product URL -- populated for reporter display only; never fetched
            if model_href:
                if model_href.startswith("http"):
                    url = model_href
                else:
                    url = _BASE_URL + model_href.lstrip("/")
            else:
                url = _BASE_URL + f"modelSearch.html?model={model_name}"

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

            # Scalar params from COLUMN_MAP
            for norm_key, (canonical, unit) in COLUMN_MAP.items():
                if canonical in ("model", "freq_low", "freq_high"):
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
  