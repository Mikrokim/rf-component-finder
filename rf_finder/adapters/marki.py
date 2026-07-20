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

Single-pass plan
----------------
This adapter extracts ONLY the parameters that appear on the all-products search
table: model, freq_range, Gain, NF, Psat, IP3 (Marki publishes OIP3), P1dB, and
the product URL.  It never fetches individual product pages.

Params NOT on the search table — Size, VDD, Temperature — are therefore left
UNKNOWN by this adapter and verify as UNKNOWN (REQ-4.1).  They are the job of the
datasheet-extraction pipeline, not this scrape.  (Historically a gated second pass
fetched each product page for these three params; that pass was removed in favour
of table-only extraction.)

MSL is likewise always UNKNOWN — it is not present anywhere in the site HTML as of
June 2026, only in datasheet PDFs.

Datasheet link (case 2): the search table's Datasheet column links to a landing
PAGE, not a PDF, so ``search()`` carries that page URL in ``datasheet_url`` and
``resolve_datasheet_url`` follows it — on demand, per candidate — to the real
``/assets/{uuid}/….pdf``.  This adapter therefore now DOES fetch beyond /search/
(one page per candidate about to be enriched); robots.txt allows both hops.

robots.txt: /search/, the per-part /…/datasheet/ pages and /assets/*.pdf are all
allowed (the file is a deny-list of named bad bots; ``*`` is unrestricted).  Compliance: browser User-Agent + a minimum delay between live fetches.
Cloudflare: a browser-style User-Agent avoids the challenge for these URLs; if a
large ``item_per_page`` is challenged, the fetch falls back to 50-per-page paging.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://markimicrowave.com"
_SEARCH_PATH = "/search/"

# Browser-style User-Agent (plain bot UAs trigger the Cloudflare challenge)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "TBD", "tbd"})

# Minimum seconds between consecutive live HTTP fetches (site asks for ~1.5s)
_MIN_DELAY_SECONDS = 1.5

# Transient network errors are retried per request.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0

# Pagination: one big page minimises requests; fall back to 50/page on challenge.
_ITEM_PER_PAGE = 200
_FALLBACK_ITEM_PER_PAGE = 50
_MAX_PAGES = 50  # safety bound for the paging loop

# ---------------------------------------------------------------------------
# Column mapping: normalised header text -> (canonical_name, source unit)
#
# Frequency columns ("flow ghz" / "fhigh ghz") are combined into freq_range
# (GHz) and handled separately.  Headers not listed here — part number, BUY NOW,
# Subfamily, Datasheet, SnP, Package Type, Status — are ignored.
# ---------------------------------------------------------------------------

# The normalised header of the column carrying the per-part datasheet LANDING
# PAGE (not the PDF), and the exact link text of the PDF on that page.  The page
# also carries two site-wide "Online Catalog" PDFs — real, parseable PDFs — so
# matching anything looser than this text would hand the extractor a catalogue
# and, because that counts as "datasheet read", DROP the part instead of
# reporting it not-verified.
_DATASHEET_COLUMN = "datasheet"
_DATASHEET_LINK_TEXT = "download pdf"

SCALAR_COLUMN_MAP: dict[str, tuple[str, str]] = {
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "psat dbm": ("Psat", "dBm"),
    "oip3 dbm": ("IP3",  "dBm"),
    "p1db dbm": ("P1dB", "dBm"),
}

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


def _row_datasheet_page(cells, data_headers: list[str]) -> str | None:
    """The href of the row's ``Datasheet`` column, absolutized — or ``None``.

    This is a landing PAGE (``/products/{package}/amplifiers/{model}/datasheet/``),
    NOT the PDF; ``resolve_datasheet_url`` follows it.  It is READ from the column
    rather than derived from the product URL: the two coincide on every live row
    today, but a constructed URL is exactly how the Mini-Circuits datasheet lookup
    failed silently.
    """
    for i, cell in enumerate(cells):
        if i >= len(data_headers) or data_headers[i] != _DATASHEET_COLUMN:
            continue
        a_tag = cell.css_first("a")
        href = (a_tag.attributes.get("href") or "") if a_tag is not None else ""
        if href:
            return urljoin(_BASE_URL, href)
    return None


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


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class MarkiMicrowaveAdapter(Adapter):
    """Scrapes Marki Microwave's amplifier catalogue for component specs."""

    manufacturer = "Marki Microwave"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the amplifier catalogue and return every row as a Candidate.

        Only the all-products search table is fetched; each row's on-table
        params are returned as-is.  Params absent from the table (Size, VDD,
        Temperature, MSL) are left UNKNOWN.  No server-side filtering is
        applied; the Verifier applies all constraints.
        """
        return self._fetch_search_candidates()

    def resolve_datasheet_url(self, cand: Candidate) -> str | None:
        """Follow the row's datasheet landing page and return the real PDF link.

        Case 2: the table's Datasheet column links to an HTML page, and the PDF
        lives on it under an ``/assets/{uuid}/`` path that cannot be constructed
        from the model — so one request per candidate is unavoidable.  The
        pipeline only calls this for candidates it is about to enrich.

        Returns ``None`` on any failure, and NEVER falls back to
        ``cand.datasheet_url`` (the base-class default does): that value is an
        HTML page, which the caller would then try to parse as a PDF.
        """
        page_url = cand.datasheet_url
        if not page_url:
            return None
        try:
            html = self._request(page_url).text
        except AdapterError:
            return None

        for a_tag in HTMLParser(html).css("a"):
            if a_tag.text(strip=True).lower() != _DATASHEET_LINK_TEXT:
                continue
            href = a_tag.attributes.get("href") or ""
            if href:
                return urljoin(page_url, href)
        return None

    # ------------------------------------------------------------------
    # Fetch + parse the search table
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

            cells = row.css("td")
            raw_params = self._row_params(cells, data_headers)
            candidates.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params=raw_params,
                    source="table",
                    # NOT the PDF: the Datasheet column links to a landing PAGE.
                    # resolve_datasheet_url turns it into the real PDF on demand.
                    datasheet_url=_row_datasheet_page(cells, data_headers),
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
    # HTTP
    # ------------------------------------------------------------------

    def _request(self, url: str) -> httpx.Response:
        """GET *url* with browser headers, rate-limited and retried.

        Enforces ``_MIN_DELAY_SECONDS`` between requests and retries transient
        failures up to ``_MAX_ATTEMPTS`` times.  Raises ``AdapterError`` only
        after every attempt fails.
        """
        last_exc: httpx.HTTPError | None = None

        for attempt in range(_MAX_ATTEMPTS):
            elapsed = time.time() - self._last_fetch_time
            if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
                time.sleep(_MIN_DELAY_SECONDS - elapsed)

            try:
                response = httpx.get(
                    url,
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
                return response
            except httpx.HTTPError as exc:
                last_exc = exc
                self._last_fetch_time = time.time()  # keep the rate limit honest
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF_SECONDS)

        raise AdapterError(
            manufacturer=self.manufacturer,
            context=f"HTTP error fetching {url} (after {_MAX_ATTEMPTS} attempts)",
            cause=last_exc,
        )

    def _fetch(self, path: str) -> str:
        """GET ``_BASE_URL + path`` and return the response text."""
        return self._request(_BASE_URL + path).text
