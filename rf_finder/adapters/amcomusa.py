"""AmcomUSA multi-category amplifier adapter (REQ-3.1, mirrors minicircuits.py).

Fetch strategy: one HTTP GET per product-category page on amcomusa.com.  Every
listing is static, server-side-rendered ASP.NET WebForms HTML — no API, no AJAX,
no JavaScript rendering required.

Two distinct page shapes:

  * Table categories (8): a ``<table id="allPnTable">`` whose data cells hold the
    numeric value as cell text, aligned 1:1 with the header columns (a
    ``ddtf-value`` attribute is read in preference when present).  Column headers
    differ per category (Pout vs Psat, MHz vs GHz), so the header row is read live
    and mapped to canonical names — never hard-coded by position.

  * Card category (1): Rackmount HPAs has no table, only product cards.  Only a
    part number + product link are recoverable from the listing, so those
    Candidates carry no parameters and verify as ``partial``.

All eight table categories map to component_type "amplifier".  Frequency is
stored in its native source unit (MHz for LNA / Medium-Power SSPA, GHz for the
rest); the Verifier normalises to canonical GHz via ``to_canonical``.

Compliance: browser User-Agent + a minimum delay between live fetches.
"""

from __future__ import annotations

import re
import time

import httpx
from selectolax.parser import HTMLParser

from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.adapters.datasheet import extract_pdf_text
from rf_finder.cache import get_cache
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.amcomusa.com"

# Browser-style User-Agent (plain bot UAs may be rejected by the CDN)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A", "TBD", "tbd"})

# Minimum seconds between consecutive live HTTP fetches (site asks for ~1.5s)
_MIN_DELAY_SECONDS = 1.5

# Transient network errors (e.g. SSL UNEXPECTED_EOF) are retried per request.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0

_TABLE_SELECTOR = "table#allPnTable"

# ---------------------------------------------------------------------------
# Categories
#
# Eight table-backed amplifier categories (all component_type "amplifier") plus
# the card-only Rackmount HPAs category, handled separately.
# ---------------------------------------------------------------------------

TABLE_CATEGORIES: list[dict[str, str]] = [
    {"name": "Low Noise Amplifiers", "slug": "low-noise-amplifier-modules"},
    {"name": "Driver Amplifiers",    "slug": "driver-amplifiers"},
    {"name": "GaAs MMIC PAs",        "slug": "gaas-mmic-pas"},
    {"name": "GaN MMIC PAs",         "slug": "gan-mmic-pas"},
    {"name": "Medium Power SSPA",    "slug": "medium-power-sspa-modules"},
    {"name": "Compact SSPA",         "slug": "compact-sspa-modules"},
    {"name": "Standard SSPA",        "slug": "standard-sspa-modules"},
    {"name": "MMIC in a Box",        "slug": "mmic-in-a-box-modules"},
]

RACKMOUNT_CATEGORY: dict[str, str] = {
    "name": "Rackmount HPAs", "slug": "rackmount-hpas",
}

# ---------------------------------------------------------------------------
# Scalar column mapping: normalised header text -> (canonical_name, source unit)
#
# Frequency columns (Fmin/Fmax) are handled specially — their unit is detected
# from the header (MHz vs GHz).  Both "Pout" and "Psat" columns map to the
# canonical "Psat"; "IP3"/"OIP3" map to canonical "IP3".
# Any header not listed here (Vd, Bias, Package, ECCN, Connector, Size...) is
# ignored.
# ---------------------------------------------------------------------------

SCALAR_COLUMN_MAP: dict[str, tuple[str, str]] = {
    "nf db":     ("NF",   "dB"),
    "gain db":   ("Gain", "dB"),
    "p1db dbm":  ("P1dB", "dBm"),
    "pout dbm":  ("Psat", "dBm"),
    "psat dbm":  ("Psat", "dBm"),
    "oip3 dbm":  ("IP3",  "dBm"),
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


def _freq_role_and_unit(norm_header: str) -> tuple[str, str] | None:
    """Classify a normalised header as a frequency bound.

    Returns ``("low"|"high", "MHz"|"GHz")`` for an Fmin/Fmax column, else None.
    """
    if norm_header.startswith("fmin"):
        role = "low"
    elif norm_header.startswith("fmax"):
        role = "high"
    else:
        return None
    unit = "MHz" if "mhz" in norm_header else "GHz"
    return role, unit


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class AmcomUSAAdapter(Adapter):
    """Scrapes all AmcomUSA amplifier category pages for component specs."""

    manufacturer = "AmcomUSA"
    supported_components = {"amplifier"}
    # IP3 is absent from every AmcomUSA HTML table; it lives only in the PDF
    # datasheet.  Declaring it here drives needs_datasheet / enrich (generic).
    datasheet_params = frozenset({"IP3"})

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0
        # model -> datasheet PDF URL, captured during table parsing for enrich()
        self._datasheet_urls: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch every amplifier category page and return all rows as Candidates.

        No server-side filtering is applied; the Verifier applies all
        constraints (REQ-4.1).  A page that returns OK but contains no product
        table yields no Candidates for that category (skipped, not an error).

        Resilience (NFR-4): each of the ~9 category pages is fetched
        independently — a page that fails is skipped so the others still return.
        ``AdapterError`` is raised only if *every* page fails.

        Datasheet retrieval is part of this search: when the spec constrains a
        datasheet-only parameter (e.g. IP3), candidates that already match every
        other parameter are enriched from their PDF datasheet before returning
        (REQ-3.8, via ``_enrich_search_results``).
        """
        candidates: list[Candidate] = []
        errors: list[str] = []

        for category in TABLE_CATEGORIES:
            try:
                html = self._fetch(f"/categories/{category['slug']}")
                candidates.extend(self._parse_table_html(html, category))
            except AdapterError as exc:
                errors.append(str(exc))  # skip this category, keep the others

        try:
            rackmount_html = self._fetch(f"/categories/{RACKMOUNT_CATEGORY['slug']}")
            candidates.extend(self._parse_rackmount_html(rackmount_html))
        except AdapterError as exc:
            errors.append(str(exc))

        # A single page hiccup must not lose the whole manufacturer; only fail
        # outright when nothing at all could be retrieved.
        if not candidates and errors:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"all {len(errors)} category fetches failed; first: {errors[0]}",
            )

        return self._enrich_search_results(spec, candidates)

    def _datasheet_text(self, candidate: Candidate) -> str | None:
        """Return the datasheet PDF text for *candidate*, or None if unavailable.

        The PDF URL was captured during ``search`` (``td.pn-pdf``).  Best-effort:
        a missing URL or any download/extract failure returns None so enrichment
        degrades silently rather than aborting the run (NFR-4).  The generic
        ``Adapter.enrich`` handles parsing and merging.
        """
        url = self._datasheet_urls.get(candidate.model)
        if not url:
            return None
        try:
            return extract_pdf_text(self._get_bytes(url))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request(self, url: str) -> httpx.Response:
        """GET *url* with the browser headers, rate-limited and retried.

        Enforces ``_MIN_DELAY_SECONDS`` between requests and retries transient
        failures (e.g. SSL ``UNEXPECTED_EOF``) up to ``_MAX_ATTEMPTS`` times.
        Raises ``AdapterError`` only after every attempt fails.
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
                self._last_fetch_time = time.time()  # keep the rate limit honest before retry
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF_SECONDS)

        raise AdapterError(
            manufacturer=self.manufacturer,
            context=f"HTTP error fetching {url} (after {_MAX_ATTEMPTS} attempts)",
            cause=last_exc,
        )

    def _get_bytes(self, url: str) -> bytes:
        """Return the body for *url* — from cache if fresh, else fetched + cached.

        A cache hit skips both the network round-trip and the rate-limit delay,
        which is what makes a repeated search effectively instant (NFR-1/NFR-2).
        """
        cached = get_cache().get(url)
        if cached is not None:
            return cached
        body = self._request(url).content
        get_cache().set(url, body)
        return body

    def _fetch(self, path: str) -> str:
        """GET ``_BASE_URL + path`` (cached) and return the response text."""
        return self._get_bytes(_BASE_URL + path).decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Parsing (exposed for tests to call directly with fixtures)
    # ------------------------------------------------------------------

    def _parse_table_html(
        self, html: str, category: dict[str, str]
    ) -> list[Candidate]:
        """Parse one table-backed category page into Candidates.

        Returns an empty list if the page has no ``allPnTable`` (some category
        slugs are parent pages without a direct product table).
        """
        tree = HTMLParser(html)
        table = tree.css_first(_TABLE_SELECTOR)
        if table is None:
            return []

        # ---- Header row -------------------------------------------------
        # Use the LAST <tr> in <thead> (earlier rows are filter/search rows).
        # col_names[0] is "product"; the technical columns follow.
        col_names: list[str] = []
        thead = table.css_first("thead")
        if thead:
            header_rows = thead.css("tr")
            if header_rows:
                last_row = header_rows[-1]
                col_names = [
                    _normalize_header(th.text(strip=True))
                    for th in last_row.css("th")
                ]

        candidates: list[Candidate] = []
        tbody = table.css_first("tbody")
        if tbody is None:
            return candidates

        for row in tbody.css("tr"):
            cells = row.css("td")
            if not cells:
                continue

            # ---- Model number + product URL ----------------------------
            # The part number lives in <td name="product"> -> <a>.
            pn_cell = row.css_first('td[name="product"]')
            a_tag = pn_cell.css_first("a") if pn_cell else None
            if a_tag is None:
                a_tag = cells[0].css_first("a")
            if a_tag is None:
                continue

            model_name = a_tag.text(strip=True)
            if not model_name:
                continue

            href = a_tag.attributes.get("href") or ""
            url = (
                href if href.startswith("http")
                else _BASE_URL + "/" + href.lstrip("/")
            ) if href else f"{_BASE_URL}/product-details/{model_name.lower()}"

            # Capture the datasheet PDF link (td.pn-pdf) for later enrich().
            pdf_a = (
                row.css_first('td.pn-pdf a[data-name="datasheet"]')
                or row.css_first("td.pn-pdf a")
            )
            if pdf_a:
                pdf_href = pdf_a.attributes.get("href") or ""
                if pdf_href:
                    self._datasheet_urls[model_name] = pdf_href

            # ---- Technical parameters ----------------------------------
            # Data cells align 1:1 with the header columns; the value is the
            # cell text (a ``ddtf-value`` attribute is preferred when present,
            # for forward-compatibility).  Each cell is read by its column
            # index and the header mapped to a canonical name; non-numeric or
            # unmapped columns — product, Vd, Package, the trailing PDF cell —
            # are skipped naturally.
            raw_params: dict[str, RawValue] = {}
            freq_low: float | None = None
            freq_high: float | None = None
            freq_unit: str = "GHz"

            for i, cell in enumerate(cells):
                if i >= len(col_names):
                    break
                norm = col_names[i]
                if not norm:
                    continue
                ddtf = cell.attributes.get("ddtf-value")
                raw_text = ddtf if (ddtf and ddtf.strip()) else cell.text(strip=True)
                value = _parse_float(raw_text)
                if value is None:
                    continue

                freq = _freq_role_and_unit(norm)
                if freq is not None:
                    role, unit = freq
                    freq_unit = unit
                    if role == "low":
                        freq_low = value
                    else:
                        freq_high = value
                    continue

                mapped = SCALAR_COLUMN_MAP.get(norm)
                if mapped is not None:
                    canonical, src_unit = mapped
                    raw_params[canonical] = RawValue(value=value, unit=src_unit)

            if freq_low is not None and freq_high is not None:
                raw_params["freq_range"] = RawValue(
                    value=(freq_low, freq_high), unit=freq_unit
                )

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

    def _parse_rackmount_html(self, html: str) -> list[Candidate]:
        """Parse the card-only Rackmount HPAs page into Candidates.

        No parametric table exists, so each Candidate carries only a model and
        link (empty ``raw_params``) and will verify as ``partial``.
        """
        tree = HTMLParser(html)
        candidates: list[Candidate] = []
        seen: set[str] = set()

        for link in tree.css('a[href*="/product-details/"]'):
            href = link.attributes.get("href") or ""
            if not href:
                continue
            part = href.split("/product-details/")[-1].strip("/")
            model = part.upper()
            if not model or model in seen:
                continue
            seen.add(model)

            url = (
                href if href.startswith("http")
                else _BASE_URL + "/" + href.lstrip("/")
            )
            candidates.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params={},
                    source="table",
                )
            )

        return candidates
