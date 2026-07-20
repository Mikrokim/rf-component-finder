"""MACOM amplifier adapter (specs/rf-component-finder/iteration2/macom-plan.md).

Fetch strategy: a single HTTP GET to the "All Amplifiers" listing page.  The
visible parametric grid (Min/Max Frequency, Gain, P1dB, PSAT, OIP3, NF, …) is
rendered client-side by JavaScript and is NOT present as a ``<table>`` in the
response.  However, the same data IS in the raw HTML: every product row carries
an HTML-entity-encoded JSON object in its ``data-part="{…}"`` attribute.  This
adapter extracts and parses those blobs — no Playwright, no per-product fetches.
One GET returns every amplifier with its specs (macom-plan.md §1, §4).

Like the Mini-Circuits adapter, this performs NO query-side filtering: it returns
all rows and the Verifier applies every constraint (REQ-3.3 fallback order: no
public API, no server-side parametric URL → scrape).

robots.txt note: the listing path is allowed for the generic ``User-agent: *``
(``Allow: /``) with ``Crawl-delay: 60``.  Because all data arrives in one page,
a single request per refresh honours that delay; the cache serves repeats.
"""

from __future__ import annotations

import html as htmlmod
import json
import re
import time

import httpx

from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.macom.com"
_ALL_AMPLIFIERS_URL = (
    _BASE_URL + "/products/rf-microwave-mmwave/amplifiers/all-amplifiers"
)

# Browser-style User-Agent (Cloudflare returns clean 200s for it; bot UAs risk
# a challenge).  Consistent with robots' ``Content-Signal: search=yes`` — this
# is a product-search retriever, not an AI-training crawler.  (macom-plan.md OQ-M1)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# robots.txt Crawl-delay: 60 — minimum seconds between consecutive live fetches.
_MIN_DELAY_SECONDS = 60.0

# Each product row: <tr data-part="{…HTML-entity-encoded JSON…}">.  Internal
# quotes are encoded as &#034;, so the attribute's real quote delimiters bound
# the JSON cleanly.  re.S: a few blobs contain literal newlines.
_DATA_PART_RE = re.compile(r'data-part="(.*?)"', re.S)

# ---------------------------------------------------------------------------
# Spec mapping: normalised MACOM specName -> (canonical ontology name, unit).
# Frequency (Min/Max) is handled specially (combined into freq_range).  Every
# other MACOM spec (Bias Voltage, Efficiency, …) is skipped — not in the
# amplifier ontology this iteration.  Units come from the ontology, NOT the
# noisy source ``uom`` field (which has stray spaces / occasional wrong units);
# the Verifier converts via to_canonical.  (macom-plan.md §5, R1)
# ---------------------------------------------------------------------------

SPEC_MAP: dict[str, tuple[str, str]] = {
    "gain":         ("Gain", "dB"),
    "output p1db":  ("P1dB", "dBm"),
    "oip3":         ("IP3", "dBm"),
    "nf":           ("NF",   "dB"),
    "noise figure": ("NF",   "dB"),   # synonym of NF
    "psat":         ("Psat", "dBm"),
}

_MIN_FREQ_KEY = "min frequency"
_MAX_FREQ_KEY = "max frequency"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_spec_name(raw: str) -> str:
    """Lowercase and collapse whitespace (handles casing and stray spaces)."""
    return re.sub(r"\s+", " ", raw.lower()).strip()


def _to_float(value: object) -> float | None:
    """Return float for numeric values; None for missing/non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class MacomAdapter(Adapter):
    """Extracts MACOM amplifier specs from the All-Amplifiers ``data-part`` JSON."""

    manufacturer = "MACOM"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec) -> list[Candidate]:  # noqa: ANN001 (QuerySpec; signature per ABC)
        """Fetch the All-Amplifiers page and return all parts as Candidates.

        No server-side filtering is applied (MACOM has none); the Verifier
        applies all constraints.
        """
        elapsed = time.time() - self._last_fetch_time
        if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
            time.sleep(_MIN_DELAY_SECONDS - elapsed)

        try:
            response = httpx.get(
                _ALL_AMPLIFIERS_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=True,
                timeout=60.0,
            )
            response.raise_for_status()
            self._last_fetch_time = time.time()
        except httpx.HTTPError as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error fetching {_ALL_AMPLIFIERS_URL}",
                cause=exc,
            ) from exc

        return self._parse_html(response.text)

    # ------------------------------------------------------------------
    # Internal parse method (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _parse_html(self, html: str) -> list[Candidate]:
        """Parse HTML; return Candidates from every ``data-part`` JSON blob.

        Raises AdapterError if NO ``data-part`` blob is found (bad HTML / site
        change).  Individual blobs that fail to parse are skipped, not fatal.
        """
        blobs = _DATA_PART_RE.findall(html)
        if not blobs:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="no data-part product rows found in HTML",
            )

        candidates: list[Candidate] = []
        for blob in blobs:
            # strict=False: a few blobs contain literal control characters
            # inside JSON strings (macom-plan.md R3).
            try:
                part = json.loads(htmlmod.unescape(blob), strict=False)
            except (json.JSONDecodeError, ValueError):
                continue  # skip a malformed row rather than abort the run
            candidate = self._build_candidate(part)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    # ------------------------------------------------------------------
    # Candidate construction
    # ------------------------------------------------------------------

    def _build_candidate(self, part: dict) -> Candidate | None:
        """Build one Candidate from a parsed ``data-part`` object.

        Returns None if the part has no part number.
        """
        model = part.get("partNumber")
        if not model:
            return None

        # specName -> value (first occurrence wins)
        by_name: dict[str, object] = {}
        for spec in part.get("specs", []):
            name = _normalize_spec_name(str(spec.get("specName", "")))
            if name and name not in by_name:
                by_name[name] = spec.get("value")

        raw_params: dict[str, RawValue] = {}

        # Frequency range: combine Min + Max Frequency (both MHz; 100% coverage).
        f_low = _to_float(by_name.get(_MIN_FREQ_KEY))
        f_high = _to_float(by_name.get(_MAX_FREQ_KEY))
        if f_low is not None and f_high is not None:
            raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="MHz")

        # Scalar params from SPEC_MAP.  First mapped source for a canonical name
        # wins (e.g. "nf" before its "noise figure" synonym).
        for spec_key, (canonical, unit) in SPEC_MAP.items():
            if canonical in raw_params:
                continue
            value = _to_float(by_name.get(spec_key))
            if value is not None:
                raw_params[canonical] = RawValue(value=value, unit=unit)

        part_url = part.get("partUrl") or f"/products/product-detail/{model}"
        url = _BASE_URL + part_url if part_url.startswith("/") else part_url

        # Datasheet (case 1): the same ``data-part`` blob carries an absolute
        # cdn.macom.com PDF link, so it costs no extra request and needs no
        # absolutizing.  ~2% of parts omit it and legitimately stay None — those
        # parts publish no datasheet at all (their product pages have none either).
        datasheet_url = str(part.get("datasheetHref") or "").strip() or None

        return Candidate(
            model=model,
            manufacturer=self.manufacturer,
            url=url,
            raw_params=raw_params,
            source="table",
            datasheet_url=datasheet_url,
        )
