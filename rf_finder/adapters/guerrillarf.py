"""Guerrilla RF amplifier adapter (REQ-3.1, design.md §6.1–6.2, T8).

Fetch strategy: single HTTP GET to /products/amplifiers.html. The page is
server-rendered and holds two amplifier tables whose rows are present in the raw
HTML (a DataTables JS lib only wraps them at runtime for sorting/paging — the
data needs no JavaScript). No API, no per-product fetches. This adapter returns
all rows and lets the Verifier apply constraints.

The page is chosen over /api/products.json because it is a superset: it adds VDD
(a real range) and exposes Min/Max frequency as separate clean columns, all in
one request. See specs/.../adapters/guerrilla-rf/t8-plan.md.

Two tables (different columns), parsed by header name:
    table#genericAmpFunctionTbl  -- LNAs / gain blocks (Gain, NF, OP1dB, OIP3, VDD)
    table#satPATbl               -- saturated power amps (Gain, OP1dB, Psat, VDD)

Parameters not on the page (Size, MSL, Temperature) are left to the datasheet
fallback. (Package (mm) is an approximate package label, not a clean dimension.)
"""

from __future__ import annotations

import re
import time

import httpx
from selectolax.parser import HTMLParser

from rf_finder.adapters.base import Adapter, AdapterError, drop_paramless, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGE_URL = "https://www.guerrilla-rf.com/products/amplifiers.html"
_DETAIL_URL = "https://www.guerrilla-rf.com/products/detail/sku/{model}"

_TABLE_IDS = ("genericAmpFunctionTbl", "satPATbl")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "NA"})

_MIN_DELAY_SECONDS = 2.0

# Normalised header text -> (canonical_name, unit | None). "model", "freq_low",
# "freq_high", and "VDD" are handled specially; the rest are scalar raw_params.
# Headers not in this dict are skipped.
COLUMN_MAP: dict[str, tuple[str, str | None]] = {
    "product":      ("model",     None),
    "min freq ghz": ("freq_low",  "GHz"),
    "max freq ghz": ("freq_high", "GHz"),
    "gain db":      ("Gain",      "dB"),
    "nf db":        ("NF",        "dB"),
    "op1db dbm":    ("P1dB",      "dBm"),
    "oip3 dbm":     ("IP3",       "dBm"),
    "psat dbm":     ("Psat",      "dBm"),
    "vdd range v":  ("VDD",       "V"),
}

_SPECIAL = frozenset({"model", "freq_low", "freq_high", "VDD"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_header(raw: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace (so 'Gain(dB)' == 'Gain (dB)')."""
    text = re.sub(r"[()/,.:\\]", " ", raw.lower())
    return re.sub(r"\s+", " ", text).strip()


def _num(cell_text: str) -> float | None:
    """Return None for missing/sentinel/non-numeric; float otherwise."""
    t = (cell_text or "").strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _range(cell_text: str) -> tuple[float, float] | None:
    """Parse a ``"low-high"`` string into a (low, high) tuple, else None."""
    parts = (cell_text or "").split("-")
    if len(parts) != 2:
        return None
    low, high = _num(parts[0]), _num(parts[1])
    if low is None or high is None:
        return None
    return (low, high)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register
class GuerrillaRFAdapter(Adapter):
    """Scrapes Guerrilla RF /products/amplifiers.html for amplifier specs."""

    manufacturer = "Guerrilla RF"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the amplifiers page and return all rows as Candidates."""
        elapsed = time.time() - self._last_fetch_time
        if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
            time.sleep(_MIN_DELAY_SECONDS - elapsed)

        try:
            response = httpx.get(
                _PAGE_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "*/*;q=0.8"
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
                context=f"HTTP error fetching {_PAGE_URL}",
                cause=exc,
            ) from exc

        return drop_paramless(self._parse_html(response.text))

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse both amplifier tables; return a combined list of Candidates.

        Raises AdapterError if none of the expected tables are found.
        """
        tree = HTMLParser(html)
        candidates: list[Candidate] = []
        found_any = False

        for table_id in _TABLE_IDS:
            table = tree.css_first(f"table#{table_id}")
            if table is None:
                continue
            found_any = True
            candidates.extend(self._parse_table(table))

        if not found_any:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"none of the expected tables {_TABLE_IDS} found in HTML",
            )

        return candidates

    def _parse_table(self, table) -> list[Candidate]:
        """Parse one amplifier table into Candidates (header-name column mapping)."""
        header_texts = [th.text(strip=True) for th in table.css("thead th")]
        if not header_texts:
            header_texts = [th.text(strip=True) for th in table.css("th")]

        col_index: dict[str, int] = {}
        for idx, raw_header in enumerate(header_texts):
            norm = _normalize_header(raw_header)
            if norm:
                col_index[norm] = idx

        tbody = table.css_first("tbody")
        if tbody is None:
            return []

        out: list[Candidate] = []
        for row in tbody.css("tr"):
            cells = row.css("td")
            if not cells:
                continue
            cell_texts = [c.text(strip=True) for c in cells]

            def _cell(norm_key: str, _texts: list[str] = cell_texts) -> str:
                idx = col_index.get(norm_key)
                if idx is None or idx >= len(_texts):
                    return ""
                return _texts[idx]

            # Model + URL from the first cell's <a>
            a_tag = cells[0].css_first("a")
            model = (a_tag.text(strip=True) if a_tag else cell_texts[0]).strip()
            if not model:
                continue
            href = a_tag.attributes.get("href", "") if a_tag else ""
            url = href if href.startswith("http") else _DETAIL_URL.format(model=model)

            raw_params: dict[str, RawValue] = {}

            # Frequency range: combine Min + Max columns (DC parts keep a 0 low edge)
            f_low = _num(_cell("min freq ghz"))
            f_high = _num(_cell("max freq ghz"))
            if f_low is not None and f_high is not None:
                raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="GHz")

            # VDD: "low-high" range string
            vdd = _range(_cell("vdd range v"))
            if vdd is not None:
                raw_params["VDD"] = RawValue(value=vdd, unit="V")

            # Scalar params
            for norm_key, (canonical, unit) in COLUMN_MAP.items():
                if canonical in _SPECIAL:
                    continue
                value = _num(_cell(norm_key))
                if value is not None:
                    raw_params[canonical] = RawValue(value=value, unit=unit)  # type: ignore[arg-type]

            out.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params=raw_params,
                    source="table",
                )
            )

        return out
