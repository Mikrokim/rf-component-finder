"""Marki Microwave amplifier adapter (REQ-3.1, design.md §6.1–6.2, T9).

Fetch strategy: paginated HTTP GET to
``/search/?item_per_page={N}&page={P}&keyword=&family=amplifiers``.  The results
table is server-side rendered by SvelteKit in the initial HTML response — no AJAX,
POST, or JavaScript rendering is required to obtain the product rows.  The total
catalogue is ~123 amplifiers (June 2026), embedded in the page as the string
``"X - Y of N"``.

Server-side spec filtering is NOT available: the F-Low/F-High/Gain/NF inputs are
client-side JavaScript only and the server returns all products for a page.  This
adapter returns ALL rows; the Verifier applies all constraints (REQ-4.1).

Live HTML structure (verified 2026-06-30, not just from research):
  * The search ``<table>`` has one ``<thead>`` header row.  ``col_names[0]`` is
    "Part Number"; the remaining headers follow in order.
  * Each ``<tbody>`` ``<tr>`` begins with a ``<th>`` carrying the part number and
    its product href (``<th><a href="/products/{pkg}/amplifiers/{slug}/">PN</a>``),
    followed by 13 ``<td>`` data cells.  The data cells therefore align to
    ``col_names[1:]`` — NOT ``col_names`` — so the part-number header is dropped
    before positional mapping (off-by-one vs a naive ``header[i] -> cell[i]``).
  * Header text is concatenated with filter-dropdown junk for "Subfamily" and
    "Package Type", and frequency headers render as ``FLow[GHz]`` / ``FHigh[GHz]``
    (square brackets), so headers are normalised (brackets stripped) and matched
    by name, never hard-coded by position.

Two-pass plan
-------------
Pass 1 (always) — the search table: model, freq_range, Gain, NF, Psat, IP3
(Marki publishes OIP3), P1dB, and the product URL.

Pass 2 (only when the query constrains Size / VDD / Temperature) — one extra GET
per candidate product page (``/products/{pkg}/amplifiers/{slug}/``) for:
  * Size        — a column on the product-page table ("{W} x {H} mm").  Stored as
                  the larger dimension in mm (the ontology models Size as a scalar
                  "max" in mm); the EVB variant row (Size "-") is ignored by
                  matching the row whose part number equals the model.
  * VDD         — from the SvelteKit JS payload ``power_supply_voltage:[{value:"5"}]``
                  (volts); first parseable value.  Bare-die parts without SnP files
                  have no such field -> VDD stays UNKNOWN.
  * Temperature — from ``temperature:"25"`` in the same payload.  This is the single
                  characterisation temperature, so it is stored as a degenerate
                  range ``(t, t)`` °C: the ontology compares Temperature with
                  "contains", and a single point honestly does not contain a wider
                  operating band (-> FAIL / UNKNOWN, never a false PASS).

Pass 2 is gated on the query to avoid ~123 product-page fetches for the common
freq/gain search; absent params simply verify as UNKNOWN (REQ-4.1).

MSL is not present anywhere in the site HTML (search table, product page, or JS
payload) as of June 2026 — only in datasheet PDFs / compliance docs, which are NOT
fetched programmatically.  MSL is therefore always left UNKNOWN; flag parts for
manual datasheet review if the Verifier requires MSL.

robots.txt: /search/ and the product pages are allowed; datasheet PDFs are not
fetched.  Compliance: browser User-Agent + a minimum delay between live fetches.
Cloudflare: a browser-style User-Agent avoids the challenge for these URLs; if a
large ``item_per_page`` is challenged, the fetch falls back to 50-per-page paging.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from rf_finder import http
from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://markimicrowave.com"
_SEARCH_PATH = "/search/"

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "TBD", "tbd"})

# Pagination: one big page minimises requests; fall back to 50/page on challenge.
_ITEM_PER_PAGE = 200
_FALLBACK_ITEM_PER_PAGE = 50
_MAX_PAGES = 50  # safety bound for the paging loop

# Params that require a per-product page fetch (Pass 2).
_PRODUCT_PAGE_PARAMS = frozenset({"Size", "VDD", "Temperature"})

# ---------------------------------------------------------------------------
# Column mapping: normalised header text -> (canonical_name, source unit)
#
# Frequency columns ("flow ghz" / "fhigh ghz") are combined into freq_range
# (GHz) and handled separately.  Headers not listed here — part number, BUY NOW,
# Subfamily, Datasheet, SnP, Package Type, Status — are ignored.
# ---------------------------------------------------------------------------

SCALAR_COLUMN_MAP: dict[str, tuple[str, str]] = {
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "psat dbm": ("Psat", "dBm"),
    "oip3 dbm": ("IP3",  "dBm"),
    "p1db dbm": ("P1dB", "dBm"),
}

# SvelteKit JS-payload field extractors (Pass 2).
_VDD_RE = re.compile(r'power_supply_voltage:\[\{value:"([^"]*)"')
_TEMP_RE = re.compile(r'temperature:"([^"]*)"')
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_header(raw: str) -> str:
    """Lowercase, replace bracket/punctuation chars with spaces, collapse runs."""
    text = raw.lower()
    text = re.sub(r"[()\[\]{}.,:/\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(cell_text: str) -> float | None:
    """Return None for missing/non-numeric sentinels; float otherwise.

    A DC-coupled lower band edge is published as "0"; ``float("0")`` keeps it as
    a valid 0.0 GHz bound rather than dropping the row to UNKNOWN.
    """
    t = cell_text.strip()
    if t in _MISSING_SENTINELS or not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _freq_role(norm_header: str) -> str | None:
    """Classify a normalised header as a frequency bound: "low" | "high" | None."""
    if norm_header.startswith("flow"):
        return "low"
    if norm_header.startswith("fhigh"):
        return "high"
    return None


def _header_names(table) -> list[str]:
    """Return normalised header names from the table's last ``<thead>`` ``<tr>``."""
    thead = table.css_first("thead")
    if thead is None:
        return []
    header_rows = thead.css("tr")
    if not header_rows:
        return []
    return [_normalize_header(th.text(strip=True)) for th in header_rows[-1].css("th")]


def _row_model_and_url(row) -> tuple[str, str] | None:
    """Extract (model, product_url) from a row's leading ``<th><a>``; None if absent."""
    a_tag = row.css_first("th a")
    if a_tag is None:
        return None
    model = a_tag.text(strip=True)
    if not model:
        return None
    href = a_tag.attributes.get("href") or ""
    if href.startswith("http"):
        url = href
    elif href:
        url = _BASE_URL + "/" + href.lstrip("/")
    else:
        url = f"{_BASE_URL}{_SEARCH_PATH}?keyword={model}"
    return model, url


def _parse_size_mm(cell_text: str) -> float | None:
    """Parse a "{W} x {H} mm" size cell into the larger dimension (mm).

    The ontology models Size as a scalar "max" in mm, so the worst-case
    (largest) dimension is the meaningful value for a footprint constraint.
    Returns None for missing/sentinel cells.
    """
    t = cell_text.strip()
    if t in _MISSING_SENTINELS or not t:
        return None
    nums = [float(m) for m in _NUMBER_RE.findall(t)]
    if not nums:
        return None
    return max(nums)


def _first_parseable(values: list[str]) -> float | None:
    """Return the first value that parses as a float, else None."""
    for v in values:
        f = _parse_float(v)
        if f is not None:
            return f
    return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class MarkiMicrowaveAdapter(Adapter):
    """Scrapes Marki Microwave's amplifier catalogue for component specs."""

    manufacturer = "Marki Microwave"
    supported_components = {"amplifier"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the amplifier catalogue and return every row as a Candidate.

        Pass 1 fetches the search table (all pages).  Pass 2 — a per-product
        page fetch for Size / VDD / Temperature — runs only when the query
        constrains one of those params, avoiding ~123 needless requests.  No
        server-side filtering is applied; the Verifier applies all constraints.
        """
        candidates = self._fetch_search_candidates()

        if self._needs_product_pages(spec):
            candidates = [self._enrich_candidate(c) for c in candidates]

        return candidates

    @staticmethod
    def _needs_product_pages(spec: QuerySpec) -> bool:
        return any(c.canonical_name in _PRODUCT_PAGE_PARAMS for c in spec.constraints)

    # ------------------------------------------------------------------
    # Pass 1 — search table
    # ------------------------------------------------------------------

    def _fetch_search_candidates(self) -> list[Candidate]:
        """Fetch all search pages and parse them into Candidates.

        Tries one large page first; on an apparent Cloudflare challenge (a page
        with no product table) it retries with smaller pages.  Pages after the
        first are only fetched while the running total is below the catalogue
        count embedded in the "X - Y of N" string.
        """
        candidates = self._page_through(_ITEM_PER_PAGE)
        if not candidates:
            candidates = self._page_through(_FALLBACK_ITEM_PER_PAGE)
        return candidates

    def _page_through(self, item_per_page: int) -> list[Candidate]:
        candidates: list[Candidate] = []
        total: int | None = None

        for page in range(1, _MAX_PAGES + 1):
            html = self._fetch(self._search_path(item_per_page, page))
            page_candidates = self._parse_search_html(html)
            if not page_candidates:
                break  # no table / empty page -> challenge or end of results
            candidates.extend(page_candidates)

            if total is None:
                total = self._parse_total(html)
            if total is not None and len(candidates) >= total:
                break

        return candidates

    @staticmethod
    def _search_path(item_per_page: int, page: int) -> str:
        return (
            f"{_SEARCH_PATH}?item_per_page={item_per_page}&page={page}"
            "&keyword=&family=amplifiers"
        )

    @staticmethod
    def _parse_total(html: str) -> int | None:
        """Extract N from the "X - Y of N" results-count string, if present."""
        match = re.search(r"\d+\s*-\s*\d+\s+of\s+(\d+)", html)
        return int(match.group(1)) if match else None

    def _parse_search_html(self, html: str) -> list[Candidate]:
        """Parse one search-results page into Candidates.

        Returns an empty list if the page has no product table (e.g. a Cloudflare
        challenge page or an out-of-range page number).
        """
        tree = HTMLParser(html)
        table = tree.css_first("table")
        if table is None:
            return []

        col_names = _header_names(table)
        if not col_names:
            return []
        # Data <td> cells align to the headers AFTER "Part Number" (a <th>).
        data_headers = col_names[1:]

        tbody = table.css_first("tbody")
        if tbody is None:
            return []

        candidates: list[Candidate] = []
        for row in tbody.css("tr"):
            model_url = _row_model_and_url(row)
            if model_url is None:
                continue
            model, url = model_url

            raw_params = self._row_params(row.css("td"), data_headers)
            candidates.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params=raw_params,
                    source="table",
                )
            )

        return candidates

    @staticmethod
    def _row_params(cells, data_headers: list[str]) -> dict[str, RawValue]:
        """Map a row's ``<td>`` cells (aligned to ``data_headers``) to RawValues."""
        raw_params: dict[str, RawValue] = {}
        freq_low: float | None = None
        freq_high: float | None = None

        for i, cell in enumerate(cells):
            if i >= len(data_headers):
                break
            norm = data_headers[i]
            if not norm:
                continue
            value = _parse_float(cell.text(strip=True))
            if value is None:
                continue

            role = _freq_role(norm)
            if role == "low":
                freq_low = value
                continue
            if role == "high":
                freq_high = value
                continue

            mapped = SCALAR_COLUMN_MAP.get(norm)
            if mapped is not None:
                canonical, unit = mapped
                raw_params[canonical] = RawValue(value=value, unit=unit)

        if freq_low is not None and freq_high is not None:
            raw_params["freq_range"] = RawValue(value=(freq_low, freq_high), unit="GHz")

        return raw_params

    # ------------------------------------------------------------------
    # Pass 2 — per-product page enrichment
    # ------------------------------------------------------------------

    def _enrich_candidate(self, candidate: Candidate) -> Candidate:
        """Return *candidate* with Size / VDD / Temperature merged from its page.

        Resilient (NFR-4): a product-page fetch or parse failure leaves those
        params UNKNOWN and returns the original candidate unchanged.
        """
        try:
            html = self._fetch(self._product_path(candidate.url))
        except AdapterError:
            return candidate

        extra = self._extract_product_details(html, candidate.model)
        if not extra:
            return candidate

        merged = dict(candidate.raw_params)
        merged.update(extra)
        return Candidate(
            model=candidate.model,
            manufacturer=candidate.manufacturer,
            url=candidate.url,
            raw_params=merged,
            source=candidate.source,
        )

    @staticmethod
    def _product_path(url: str) -> str:
        """Return the path portion of a product URL for fetching."""
        if url.startswith(_BASE_URL):
            return url[len(_BASE_URL):]
        return url

    def _extract_product_details(self, html: str, model: str) -> dict[str, RawValue]:
        """Extract Size (table) and VDD / Temperature (JS payload) for *model*."""
        extra: dict[str, RawValue] = {}

        size = self._extract_size(html, model)
        if size is not None:
            extra["Size"] = RawValue(value=size, unit="mm")

        vdd = _first_parseable(_VDD_RE.findall(html))
        if vdd is not None:
            extra["VDD"] = RawValue(value=vdd, unit="V")

        temp = _first_parseable(_TEMP_RE.findall(html))
        if temp is not None:
            # Single characterisation point -> degenerate (t, t) range for the
            # ontology's "contains" comparison; never a false PASS for a band.
            extra["Temperature"] = RawValue(value=(temp, temp), unit="degC")

        return extra

    @staticmethod
    def _extract_size(html: str, model: str) -> float | None:
        """Return the Size (largest dim, mm) from the product table row for *model*.

        The product table carries a "Size" column and one row per variant; the
        EVB row lists Size "-", so the row whose part number equals *model* is
        selected.
        """
        tree = HTMLParser(html)
        table = tree.css_first("table")
        if table is None:
            return None

        col_names = _header_names(table)
        size_idx = next(
            (i for i, h in enumerate(col_names) if h.startswith("size")), None
        )
        if size_idx is None or size_idx == 0:
            return None
        # td cells align to col_names[1:], so the Size td is at size_idx - 1.
        td_size_idx = size_idx - 1

        tbody = table.css_first("tbody")
        if tbody is None:
            return None

        target = model.strip().lower()
        for row in tbody.css("tr"):
            a_tag = row.css_first("th a")
            if a_tag is None or a_tag.text(strip=True).strip().lower() != target:
                continue
            cells = row.css("td")
            if td_size_idx < len(cells):
                return _parse_size_mm(cells[td_size_idx].text(strip=True))
            return None
        return None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _fetch(self, path: str) -> str:
        """GET ``_BASE_URL + path`` (cache-first) and return the response text.

        Serves both the Pass-1 search pages and the Pass-2 per-product pages —
        no special handling; both ride the same cache path. The shared provider
        owns the User-Agent, the 1.5 s delay, the timeout and retries. Raises
        ``AdapterError`` when a page is unreachable with no cached copy.
        """
        url = _BASE_URL + path
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
                context=f"HTTP error fetching {url}",
            )
        return result.text
