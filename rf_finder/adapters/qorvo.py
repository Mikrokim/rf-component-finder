"""Qorvo amplifier adapter (REQ-3.1, T8).

Fetch strategy: a single HTTP GET to ``/products/product-list/`` **with no query
string**. That page is server-rendered and holds the *entire* Qorvo catalogue
(77 category tables / ~1000 parts) in the raw HTML — no JavaScript, no API. The
parametric ``?categoryID=…`` form and the ``/api`` endpoints are robots.txt
-disallowed (``Disallow: /*?*`` and ``Disallow: /api``); this compliant page is a
superset of them. See specs/.../adapters/qorvo/t8-plan.md.

Structure: ``div.static-tables-container`` → one ``div.pst`` block per category,
each with an ``h3.pst-header-title`` (category name + a ``(N)`` badge) and a
``table.pst-table``. The header row is ``<th>`` cells carrying a
``div.pst-col-header-title`` (name) and an optional ``div.pst-col-header-subtitle``
(**unit**); data rows are ``<td>`` cells whose value sits in ``div.pst-data`` and
whose part number is an ``a.pst-part-ref-name`` (``/products/p/{model}``).

This adapter keeps only the 12 amplifier categories (by title), maps columns by
header name (unit read per-column from the subtitle — frequency is GHz in most
categories but MHz in the CATV/Driver/Gain-Block ones), and returns all their
rows; the Verifier applies constraints.

Qorvo cells are messier than the other sources, so ``_num`` is more defensive:
it strips a leading ``>``/``<`` (``"> 40"`` → 40, a guaranteed value that is
conservatively correct for min/max) and takes the first numeric token (so
``"35 (S21)"``/``"18 Vdc"`` parse). ``VDD`` may list several supply options
(``"3, 5, 8"``, ``"5/8"``) → stored as the ``(min, max)`` band.

Parameters not on the page (Size, MSL, Temperature) are left to the datasheet
fallback — see t8-plan.md §6.
"""

from __future__ import annotations

import logging
import re
import time

import httpx
from selectolax.parser import HTMLParser

from rf_finder.adapters.base import Adapter, AdapterError, drop_paramless, register
from rf_finder.models import Candidate, QuerySpec, RawValue

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGE_URL = "https://www.qorvo.com/products/product-list/"   # NO query string
_ORIGIN = "https://www.qorvo.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "--", "n/a", "N/A", "NA", "na"})

_MIN_DELAY_SECONDS = 2.0

# Normalised h3 titles (badge stripped) of the 12 amplifier categories we keep.
AMP_CATEGORIES = frozenset({
    "catv amplifiers",
    "catv hybrid amplifiers",
    "digital variable gain amplifiers",
    "distributed amplifiers",
    "driver amplifiers",
    "gain block amplifiers",
    "high frequency amplifiers",
    "low noise amplifiers",
    "low noise amplifiers with bypass",
    "low phase noise amplifiers",
    "power amplifiers",
    "spatium amplifiers",
})

# Normalised column-header title -> canonical scalar param. Frequency Min/Max and
# the VDD headers are handled specially (see below), not via this map. "Power
# Gain" is intentionally absent: for Spatium we take "Small Signal Gain" so Gain
# is comparable with the plain "Gain" of the other 11 categories (see
# requirements.md QRV-OQ-1).
COLUMN_MAP: dict[str, str] = {
    "gain": "Gain",
    "small signal gain": "Gain",
    "gain 0 db atten": "Gain",   # Digital VGA: "Gain @ 0 dB Atten"
    "op1db": "P1dB",
    "oip3": "IP3",
    "nf": "NF",
    "psat": "Psat",
}

_FREQ_MIN = "frequency min"
_FREQ_MAX = "frequency max"
_VDD_TITLES = frozenset({"voltage", "vd"})   # GaN parts label supply "Vd"; "Vg" ignored


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEADING_CMP = re.compile(r"^\s*[<>~]=?\s*")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def _norm(raw: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace ('Gain @ 0 dB' == 'gain 0 db')."""
    text = re.sub(r"[()/,.:@\\]", " ", (raw or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _category_name(h3_text: str) -> str:
    """Category title without the trailing ``(N)`` badge, lowercased/space-collapsed."""
    return " ".join(h3_text.split("(")[0].split()).lower()


def _num(cell_text: str) -> float | None:
    """Parse one Qorvo cell to a float (defensively), else None.

    Handles the messy formats Qorvo uses: missing sentinels / ``""`` → None;
    ``"DC"`` → 0.0; a leading ``>``/``<``/``~`` comparator is stripped (``"> 40"``
    → 40.0); then the first numeric token is taken, so trailing qualifiers and
    units are ignored (``"35 (S21)"`` → 35, ``"18 Vdc"`` → 18). A thousands-grouped
    integer (``"1,000"``) is de-grouped; a comma/slash *list* (``"9, 11"``,
    ``"5/8"``) yields its first value.
    """
    t = (cell_text or "").strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    if t.upper() == "DC":
        return 0.0
    t = _LEADING_CMP.sub("", t)
    if _THOUSANDS.match(t):
        t = t.replace(",", "")
    m = _NUM_RE.search(t)
    return float(m.group()) if m else None


def _vdd(cell_text: str) -> tuple[float, float] | list[float] | None:
    """Parse a supply-voltage cell, else None.

    Two shapes, distinguished by the cell's syntax:

    - a **continuous range** (``"2 to 4.5"`` → ``(2.0, 4.5)``) or a single value
      (``"30"`` → ``(30.0, 30.0)``) is returned as a ``(low, high)`` tuple;
    - **discrete supply options** delimited by ``,`` or ``/`` (``"3, 5, 8"`` →
      ``[3.0, 5.0, 8.0]``, ``"5/8"`` → ``[5.0, 8.0]``) are returned as a ``list``.

    The distinction matters for matching: a part offering 3/5/8 V does NOT
    support 4 V, whereas a 2–4.5 V range does. A leading comparator is stripped
    and a trailing unit ignored (``"18 Vdc"`` → ``(18.0, 18.0)``).

    An unrecognised multi-value shape (2+ numbers, no ``to`` and no ``,``/``/``)
    is logged and falls back to ``(min, max)`` — the pre-list behaviour, so a
    novel format never crashes or silently misclassifies as a discrete list.
    """
    t = (cell_text or "").strip()
    if not t or t in _MISSING_SENTINELS:
        return None
    body = _LEADING_CMP.sub("", t)
    nums = [float(x) for x in _NUM_RE.findall(body)]
    if not nums:
        return None
    if len(nums) == 1:
        return (nums[0], nums[0])
    if "," in body or "/" in body:
        # Discrete options — de-duplicate, ascending, for a stable value.
        return sorted(set(nums))
    if "to" in body.lower():
        return (min(nums), max(nums))
    _log.warning("Qorvo _vdd: unrecognised multi-value supply %r → range fallback", t)
    return (min(nums), max(nums))


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@register
class QorvoAdapter(Adapter):
    """Scrapes Qorvo /products/product-list/ for amplifier specs."""

    manufacturer = "Qorvo"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the product-list page and return all amplifier rows as Candidates."""
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
                timeout=60.0,   # ~5.3 MB page
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
        """Parse every amplifier-category block; return a combined Candidate list.

        Raises AdapterError if the product-list container is absent.
        """
        tree = HTMLParser(html)
        container = tree.css_first("div.static-tables-container")
        if container is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="product-list container (div.static-tables-container) not found in HTML",
            )

        candidates: list[Candidate] = []
        for block in container.css("div.pst"):
            h3 = block.css_first("h3.pst-header-title")
            if h3 is None:
                continue
            if _category_name(h3.text()) not in AMP_CATEGORIES:
                continue
            candidates.extend(self._parse_block(block))
        return candidates

    def _parse_block(self, block) -> list[Candidate]:
        """Parse one amplifier category block into Candidates (header-name mapping)."""
        table = block.css_first("table.pst-table")
        if table is None:
            return []

        # Column layout from the header <th> cells: index -> (norm title, unit).
        columns: list[tuple[str, str]] = []
        for th in table.css("th"):
            title_el = th.css_first(".pst-col-header-title")
            unit_el = th.css_first(".pst-col-header-subtitle")
            title = _norm(title_el.text(strip=True)) if title_el else ""
            unit = unit_el.text(strip=True) if unit_el else ""
            columns.append((title, unit))

        out: list[Candidate] = []
        for row in table.css("tbody tr"):
            cells = row.css("td")
            if not cells:
                continue  # the header row (all <th>)
            anchor = cells[0].css_first("a.pst-part-ref-name")
            if anchor is None:
                continue
            model = anchor.text(strip=True)
            if not model:
                continue
            href = anchor.attributes.get("href", "") or ""
            url = href if href.startswith("http") else _ORIGIN + href

            raw_params: dict[str, RawValue] = {}
            freq_low: float | None = None
            freq_high: float | None = None
            freq_unit = ""

            for idx, cell in enumerate(cells):
                if idx >= len(columns):
                    break
                title, unit = columns[idx]
                if not title:
                    continue
                data_el = cell.css_first(".pst-data")
                text = data_el.text(strip=True) if data_el else cell.text(strip=True)

                if title == _FREQ_MIN:
                    freq_low = _num(text)
                    freq_unit = unit or freq_unit
                elif title == _FREQ_MAX:
                    freq_high = _num(text)
                    freq_unit = freq_unit or unit
                elif title in _VDD_TITLES:
                    vdd = _vdd(text)
                    if vdd is not None:
                        raw_params["VDD"] = RawValue(value=vdd, unit=unit or "V")
                else:
                    canonical = COLUMN_MAP.get(title)
                    if canonical is None:
                        continue
                    value = _num(text)
                    if value is not None:
                        raw_params[canonical] = RawValue(value=value, unit=unit)

            if freq_low is not None and freq_high is not None:
                raw_params["freq_range"] = RawValue(
                    value=(freq_low, freq_high), unit=freq_unit or "GHz"
                )

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
