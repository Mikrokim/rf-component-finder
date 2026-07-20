"""RWM (rwmmic.com) amplifier adapter (REQ-3.1, design.md §6.1–6.2, mirrors minicircuits.py).

Fetch strategy: a single HTTP GET to the site's JSON product API
``/index.php?r=api/all-products`` — it returns the ENTIRE catalogue (every
category, its field definitions, and all products with their spec values) in one
response.  The visible ``/product.html`` page is an almost-empty shell that loads
this same endpoint client-side via axios; there is no HTML table to scrape, so we
call the API directly (confirmed live: the page's JavaScript calls
``api/all-products`` and ``api/category-menu``).

Server-side spec filtering is NOT available: the API always returns the whole
catalogue.  This adapter selects the amplifier categories, returns ALL of their
rows, and the Verifier applies all constraints (REQ-4.1).

Amplifier selection: the catalogue groups products by category.  Every amplifier
category's name contains the word "Amplifier" (Low Noise, Low Noise with Limiter,
Distributed, Driver, Power, GaN Power — bare-die and packaged), and no
non-amplifier category does, so groups are selected by that substring.  This is
robust to the category-tree quirk where "Low Noise Amplifiers with Limiter" sits
as a direct child of "Amplifiers" rather than under the LNA sub-tree.

Field mapping is by field NAME (not position): the columns differ per category —
LNAs publish "Gain (dB)" and "Voltage (V)", GaN PAs publish "Small Signal Gain
(dB)", "Psat (dBm)" and "Vd (V)".  Gain is taken ONLY from the field whose exact
on-site label is "Gain (dB)"; "Small Signal Gain" and "Power Gain" are distinct
measurements and are deliberately NOT treated as Gain — so GaN PAs, which have no
plain "Gain (dB)" column, get Gain UNKNOWN.  Both supply columns ("Voltage (V)"
and "Vd (V)") map to canonical VDD.  IP3/OIP3 is not published by rwmmic, so it
stays UNKNOWN.  Frequencies are in GHz (Verifier normalises).

Operating points: some parts (~42) are characterised at several coupled bias
points, published as "/"-separated per-point values that align by position
across fields (e.g. RW3010: Gain "24/23.5", Voltage "5/6").  The adapter emits
ONE Candidate per operating point so each stays self-consistent (the Verifier
never mixes a Gain from one bias with a Psat from another); single-valued fields
(e.g. the frequency band) are shared across all points.  See
``_product_to_candidates``.

TLS note: rwmmic.com serves a self-signed certificate in its chain, so strict
verification fails (verified live — a control fetch of another vendor succeeds
with verification on).  ``_VERIFY_TLS`` is therefore False for this host; flip it
to True on a network that trusts the site's certificate.

robots.txt note: ``Disallow:`` is empty (everything allowed), including the
datasheet PDF path.

Datasheet link (case 1): every product's ``Datasheet`` field carries an absolute
PDF URL in the same JSON response, so ``search()`` fills ``datasheet_url``
directly — no extra request.  ``Candidate.url`` is the catalogue page filtered to
the product's category (``product.html?category=<id>``): rwmmic publishes no
per-part page at all, since ``product.html`` is an SPA whose only deep links are
per-category.
"""

from __future__ import annotations

import json
import re
import time

import httpx

from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://www.rwmmic.com/"
_ALL_PRODUCTS_URL = _BASE_URL + "index.php?r=api/all-products"

# Browser-style User-Agent (plain bot UAs may be rejected by the CDN)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "N/A"})

# Minimum seconds between consecutive live HTTP fetches
_MIN_DELAY_SECONDS = 1.0

# rwmmic.com serves a self-signed cert in its chain; strict verification fails.
_VERIFY_TLS = False

# Amplifier categories are exactly those whose name contains this token.
_AMPLIFIER_KEYWORD = "amplifier"

# Canonical Gain is taken ONLY from the field whose exact on-site label is this
# string — never from "Small Signal Gain (dB)" or "Power Gain (dB)".
_GAIN_FIELD = "Gain (dB)"

# ---------------------------------------------------------------------------
# Field mapping: normalised field name -> (canonical_name, unit | None)
# "model", "freq_low", "freq_high" are handled specially; all others map to
# raw_params.  Field names not in this dict (Type, Package, Current, PAE, Id,
# Power Gain, Datasheet, …) are skipped.  Gain is NOT here — it is matched by its
# exact on-site label (see _GAIN_FIELD).  Both "Voltage (V)" and "Vd (V)" map to
# canonical VDD.
# ---------------------------------------------------------------------------

FIELD_MAP: dict[str, tuple[str, str | None]] = {
    "pn":                    ("model",     None),
    "freq low ghz":          ("freq_low",  "GHz"),
    "freq high ghz":         ("freq_high", "GHz"),
    "nf db":                 ("NF",        "dB"),
    "p1db dbm":              ("P1dB",      "dBm"),
    "psat dbm":              ("Psat",      "dBm"),
    "voltage v":             ("VDD",       "V"),
    "vd v":                  ("VDD",       "V"),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_field(raw: str) -> str:
    """Lowercase, remove punctuation characters, collapse whitespace."""
    text = raw.lower()
    text = re.sub(r"[()\[\].,:/\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_values(cell_text: str) -> list[str]:
    """Split a coupled per-operating-point cell on "/" into its parts.

    "24/23.5" -> ["24", "23.5"]; a plain single value -> a 1-element list; an
    empty/whitespace cell -> [].  A negative sign is not a separator, so values
    like "+5/-5" still split into ["+5", "-5"] (each then parsed on its own).
    """
    return [part.strip() for part in cell_text.split("/") if part.strip()]


def _parse_float(cell_text: str) -> float | None:
    """Return None for missing/non-numeric sentinels; float otherwise.

    rwmmic encodes a DC-coupled lower band edge as the literal "DC" (0 Hz); map
    it to 0.0 so the ~27 DC-coupled amplifiers keep a usable freq_range instead
    of being dropped to UNKNOWN.  Dual per-band values such as "27/25" or "+5/-5"
    are not a single float, so they return None (the param stays UNKNOWN) — safe,
    never a false match.
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
class RwmmicAdapter(Adapter):
    """Fetches rwmmic.com's JSON product API and returns amplifier specs."""

    manufacturer = "RWM"
    supported_components = {"amplifier"}

    def __init__(self) -> None:
        self._last_fetch_time: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Fetch the full catalogue and return every amplifier row as a Candidate.

        No server-side filtering is applied — the API always returns the whole
        catalogue.  The Verifier applies all constraints (REQ-4.1).
        """
        return self._parse_json(self._fetch_json())

    def _fetch_json(self) -> str:
        """GET the all-products API and return the response text, rate-limited."""
        # Enforce minimum inter-request delay
        elapsed = time.time() - self._last_fetch_time
        if self._last_fetch_time and elapsed < _MIN_DELAY_SECONDS:
            time.sleep(_MIN_DELAY_SECONDS - elapsed)

        try:
            response = httpx.get(
                _ALL_PRODUCTS_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/json, text/javascript, */*;q=0.1",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": _BASE_URL + "product.html",
                },
                follow_redirects=True,
                timeout=30.0,
                verify=_VERIFY_TLS,
            )
            response.raise_for_status()
            self._last_fetch_time = time.time()
        except httpx.HTTPError as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error fetching {_ALL_PRODUCTS_URL}",
                cause=exc,
            ) from exc

        return response.text

    # ------------------------------------------------------------------
    # Internal parse method (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> list[Candidate]:
        """Parse the all-products JSON body into Candidates.

        Raises AdapterError if the body is not valid JSON or lacks a 'data'
        array of category groups.
        """
        try:
            doc = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="response body is not valid JSON",
                cause=exc,
            ) from exc

        groups = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(groups, list):
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="all-products JSON has no 'data' array",
            )

        candidates: list[Candidate] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            category = group.get("category") or {}
            name = str(category.get("name", ""))
            if _AMPLIFIER_KEYWORD not in name.lower():
                continue  # skip switches, mixers, attenuators, filters, …

            category_id = category.get("id")
            for product in group.get("products") or []:
                candidates.extend(self._product_to_candidates(product, category_id))

        return candidates

    def _product_to_candidates(
        self, product: dict, category_id: object = None
    ) -> list[Candidate]:
        """Convert one product record into one Candidate PER operating point.

        Some parts are characterised at several coupled operating points (bias
        conditions), published as "/"-separated per-point values that align by
        position across fields — e.g. RW3010 has Gain "24/23.5", P1dB "27/29",
        Voltage "5/6" (24 dB gain is the Vd=5 V point, 23.5 dB the Vd=6 V point).
        Emitting one Candidate per point keeps each point self-consistent so the
        Verifier never mixes values from different conditions (Gain 24 with
        P1dB 29 is not a real operating point).  Single-valued fields (e.g. the
        frequency band) are shared across every point.  Returns [] if unusable.
        """
        if not isinstance(product, dict):
            return []

        # Collect field values keyed by both the exact on-site label and the
        # normalised field name.  Gain is matched by exact label (_GAIN_FIELD);
        # the other params tolerate label variants via the normalised key.
        values: dict[str, str] = {}          # normalised name -> value
        values_exact: dict[str, str] = {}    # exact on-site label -> value
        for fv in product.get("field_values") or []:
            raw_name = str(fv.get("field_name", ""))
            value = str(fv.get("value", ""))
            values_exact[raw_name] = value
            norm = _normalize_field(raw_name)
            if norm:
                values[norm] = value

        # Model: the product 'name', falling back to the PN field.
        model_name = str(product.get("name", "")).strip() or values.get("pn", "").strip()
        if not model_name:
            return []

        # Datasheet: the API publishes an absolute PDF link per product (case 1),
        # so it needs no extra request and no absolutizing.
        datasheet_url = values.get("datasheet", "").strip() or None

        # Product URL: rwmmic has NO per-part page — product.html is an SPA whose
        # only deep links are per-category — so the closest thing to a product
        # page is the catalogue filtered to this product's category.
        url = _BASE_URL + "product.html"
        if category_id is not None:
            url = f"{url}?category={category_id}"

        # ---- Gather the per-field value lists (split coupled "/" values) -----
        # Each entry: (canonical_name, unit, [value, ...]).  Frequency bounds are
        # kept separate because they combine into one freq_range.
        f_low_parts = _split_values(values.get("freq low ghz", ""))
        f_high_parts = _split_values(values.get("freq high ghz", ""))

        scalar_parts: list[tuple[str, str, list[str]]] = []
        gain_parts = _split_values(values_exact.get(_GAIN_FIELD, ""))
        if gain_parts:
            scalar_parts.append(("Gain", "dB", gain_parts))
        for norm_key, (canonical, unit) in FIELD_MAP.items():
            if canonical in ("model", "freq_low", "freq_high"):
                continue
            parts = _split_values(values.get(norm_key, ""))
            if parts:
                scalar_parts.append((canonical, unit, parts))  # type: ignore[arg-type]

        # ---- Determine the number of operating points N ---------------------
        # N is the common count of the multi-valued fields.  If those counts
        # disagree (never seen live), fall back to a single point and drop the
        # multi-valued fields (they stay UNKNOWN) — safe, never a mixed point.
        all_lists = [f_low_parts, f_high_parts] + [p for _, _, p in scalar_parts]
        multi_counts = {len(p) for p in all_lists if len(p) > 1}
        if not multi_counts:
            n_points, consistent = 1, True
        elif len(multi_counts) == 1:
            n_points, consistent = multi_counts.pop(), True
        else:
            n_points, consistent = 1, False

        def _pick(parts: list[str], i: int) -> float | None:
            """Value for point i: shared single value, or the i-th of N; else None."""
            if len(parts) == 1:
                return _parse_float(parts[0])          # single value shared across points
            if consistent and len(parts) == n_points:
                return _parse_float(parts[i])           # coupled per-point value
            return None                                 # mismatched multi-field -> UNKNOWN

        # ---- Build one Candidate per operating point ------------------------
        candidates: list[Candidate] = []
        for i in range(n_points):
            raw_params: dict[str, RawValue] = {}

            f_low = _pick(f_low_parts, i)
            f_high = _pick(f_high_parts, i)
            if f_low is not None and f_high is not None:
                raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="GHz")

            for canonical, unit, parts in scalar_parts:
                val = _pick(parts, i)
                if val is not None:
                    raw_params[canonical] = RawValue(value=val, unit=unit)

            # Label each point when there is more than one, so the same PN is
            # distinguishable in results (the per-point VDD is in raw_params).
            model = model_name if n_points == 1 else f"{model_name} (op {i + 1}/{n_points})"
            candidates.append(
                Candidate(
                    model=model,
                    manufacturer=self.manufacturer,
                    url=url,
                    raw_params=raw_params,
                    source="table",
                    datasheet_url=datasheet_url,
                )
            )

        return candidates
