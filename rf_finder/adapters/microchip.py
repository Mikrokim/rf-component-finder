"""Microchip amplifier adapter (specs/rf-component-finder/iteration2/microchip-plan.md).

Fetch strategy: **official JSON API, no scraping.** ``www.microchip.com`` is hard
-blocked by Akamai (403 even with a browser User-Agent), so the human-facing
parametric-search tables cannot be fetched.  Instead the data is assembled from
two open JSON hosts in a **three-hop chain**:

    1. MCP ``search_products``              -> enumerate part numbers
       (api.microchip.com, public/no-auth; text search, so union several
        amplifier terms and paginate).
    2. MCP ``search_product_physical_specs`` -> per part: the ``parametricData``
       feed URL, plus package size (Size) and MSL.
    3. GET ``<parametricData>`` (microchipdirect feed) -> the RF electrical specs
       (Freq, Gain, NF, OIP3, P1dB, Pout, Bias).

The MCP ``search_products`` text search is *polluted* (it returns op-amps, HV
drivers, SerDes limiting amps for "amplifier"), so each candidate feed is gated
by its ``product_type`` field: only the RF-MMIC feeds carry ``product_type`` at
all, and we keep only those whose value names an amplifier/LNA (microchip-plan §2,
§6, R2).

Like the other adapters this performs NO query-side filtering: it returns every
amplifier and the Verifier applies all constraints (REQ-4.1).  MCP responses are
SSE-framed JSON-RPC whose payload is a JSON *string* under
``result.content[0].text`` (microchip-plan §4, R4).
"""

from __future__ import annotations

import dataclasses
import json
import re
from concurrent.futures import ThreadPoolExecutor

from rf_finder import http
from rf_finder.adapters.base import Adapter, AdapterError, register
from rf_finder.models import Candidate, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MCP_URL = "https://api.microchip.com/mcp/resources"
# Feed URLs are read from each part's ``parametricData`` field — never built by
# hand (the slug is not derivable from the part number; microchip-plan §2, R3).

# Browser-style User-Agent (honest product-search retriever).  microchipdirect
# feeds and the MCP host both return clean 200s for it.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# MCP streamable-HTTP requires this Accept; ``tools/call`` works stateless (no
# initialize handshake needed — microchip-plan §4).
_MCP_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_FEED_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json,*/*;q=0.8",
}

# Curated amplifier search terms.  Text search overlaps heavily, so the union is
# de-duplicated by part number; the ``product_type`` gate drops non-amplifiers
# that these terms drag in (microchip-plan §2/OQ-1).  "prescaler" is deliberately
# excluded — a prescaler is a divider, not an amplifier.
_AMPLIFIER_TERMS = (
    "low noise amplifier",
    "power amplifier",
    "distributed amplifier",
    "driver amplifier",
    "wideband amplifier",
    "gain block",
    "MMIC amplifier",
)
_SEARCH_LIMIT = 60  # MCP maximum per page

# A feed is an RF amplifier iff it has a ``product_type`` naming one of these.
# Observed values: "Power Amplifier", "Distributed Low Noise Amplifier",
# "Distributed Amplifier", "Wideband Low Noise Amplifier", "Wideband Amplifier",
# "Distributed Power-Amplifer (Driver)" (sic — note the misspelling, which is why
# the marker is "amplif", not "amplifier"), "Low Noise Amplifier".
_AMPLIFIER_TYPE_MARKERS = ("amplif", "lna", "gain block")

# Concurrency cap for the per-part fetches.  The MCP tools are documented
# PARALLEL-SAFE (read-only, stateless), so we fan out with a bounded thread pool
# rather than a serial delay — fast but still polite (microchip-plan §3, §4/OQ-3).
_MAX_WORKERS = 8

_MISSING_SENTINELS = frozenset({"", "-", "n/a", "na", "—", "tbd", "none"})

# ---------------------------------------------------------------------------
# Feed key -> (canonical ontology name, unit).  Keyed by the *normalised* feed
# key (see _normalize_key).  Frequency and VDD are handled specially below; every
# other feed field (PAE, Gain Flatness, Package, IIP3, device-family ids, …) is
# skipped — not in the amplifier ontology (microchip-plan §5, §6).
# ---------------------------------------------------------------------------

FEED_MAP: dict[str, tuple[str, str]] = {
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "oip3 dbm": ("IP3",  "dBm"),   # output IP3; IIP3 (input) is intentionally ignored
    "p1db dbm": ("P1dB", "dBm"),   # source key is the oddly-cased "p1db(dBM)"
    "pout dbm": ("Psat", "dBm"),   # power amps publish saturated power as "Pout (dBm)"
}

_FREQ_MIN_KEY = "freq min ghz"
_FREQ_MAX_KEY = "freq max ghz"
_BIAS_KEY = "bias"
_VOLTAGE_KEY = "voltage v"  # some power-amp feeds give "Voltage (V)" instead of "Bias"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_key(raw: str) -> str:
    """Lowercase, drop punctuation (parens, +/-, slashes, dots), collapse space.

    Folds e.g. ``"p1db(dBM)"`` -> ``"p1db dbm"`` and ``"Freq Min GHz"`` ->
    ``"freq min ghz"`` so the map keys stay readable and robust to punctuation
    and casing drift.
    """
    text = re.sub(r"[()+/\\.,:±%-]", " ", raw.lower())
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(value: object) -> float | None:
    """Return float for numeric values; None for missing / sentinel / non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in _MISSING_SENTINELS:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    # Some feed cells carry a trailing unit ("28 dBm", "17 dB") instead of a bare
    # number — an inconsistency in how a part is published, not a real absence.
    # Take the leading numeric token so the value isn't lost as UNKNOWN (which
    # would wrongly hide the part). Applies to every scalar parsed here.
    match = re.match(r"[-+]?\d*\.?\d+", text)
    return float(match.group()) if match else None


def _parse_freq(value: object) -> float | None:
    """Parse a feed frequency cell in GHz; ``"DC"`` -> 0.0 (band edge)."""
    if value is not None and str(value).strip().lower() == "dc":
        return 0.0
    return _parse_float(value)


def _parse_bias_volts(bias: object) -> float | None:
    """Extract the supply voltage from a ``Bias`` string like ``"4V, 80mA"``."""
    if bias is None:
        return None
    match = re.search(r"([\d.]+)\s*[Vv]", str(bias))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _parse_size_mm(pkg: object) -> float | None:
    """Largest package edge in mm from ``"L x W x H mm"`` (footprint bound).

    Size in the ontology is a single ``max`` scalar; the source is a 3-D
    dimension string, so we take the largest numeric dimension — "the part's
    largest edge fits within X mm" (microchip-plan §5/OQ-7).
    """
    if pkg is None:
        return None
    nums: list[float] = []
    for token in re.findall(r"[\d.]+", str(pkg)):
        try:
            nums.append(float(token))
        except ValueError:
            continue  # skip a malformed token like "1.2.3"
    return max(nums) if nums else None


def _parse_msl(msl: object) -> float | None:
    """Parse an MSL level from ``"MSL-1"`` etc.; None if absent/unparseable."""
    if msl is None:
        return None
    match = re.search(r"(\d+)", str(msl))
    return float(match.group(1)) if match else None


def _is_amplifier(feed: dict) -> bool:
    """True iff the feed's ``product_type`` names an amplifier / LNA.

    Only RF-MMIC feeds carry ``product_type`` at all; op-amp / PGA / MCU feeds
    have entirely different schemas and no such key, so this both filters the
    text-search pollution and confirms we parsed a real parametric feed.
    """
    pt = feed.get("product_type")
    if not isinstance(pt, str):
        return False
    low = pt.lower()
    return any(marker in low for marker in _AMPLIFIER_TYPE_MARKERS)


# Packaging-variant suffixes: the same die on a different reel/pack shares ONE
# datasheet, but the MCP often returns ``datasheetUrl`` only on the base part.
# Longest first so "/TR" is stripped before the bare "TR".
_VARIANT_SUFFIXES = ("/TR", "TR", "E")


def _base_part(model: str) -> str:
    """Strip a trailing packaging-variant suffix (``/TR`` / ``TR`` / ``E``).

    ``MMA047PP4TR`` -> ``MMA047PP4``; ``MMA085PP4E`` -> ``MMA085PP4``;
    ``MMA043PP4/TR`` -> ``MMA043PP4``.  A part with no such suffix is returned
    unchanged, so a base part maps to itself.
    """
    for suffix in _VARIANT_SUFFIXES:
        if model.endswith(suffix) and len(model) > len(suffix):
            return model[: -len(suffix)]
    return model


def _fill_variant_datasheets(candidates: list[Candidate]) -> list[Candidate]:
    """Give a link-less candidate its packaging base part's datasheet, if any.

    A candidate whose ``datasheet_url`` is None inherits the link of a sibling
    that shares its base part number (same die, one datasheet) — taken ONLY from
    THIS already-fetched result set, so no extra request is made.  When no linked
    sibling exists the candidate stays None (unchanged behaviour: D7 condition 1).
    This can only add coverage, never remove or change an existing link.
    """
    by_base: dict[str, str] = {}
    for cand in candidates:
        if cand.datasheet_url:
            by_base.setdefault(_base_part(cand.model), cand.datasheet_url)
    if not by_base:
        return candidates
    return [
        cand
        if cand.datasheet_url
        else dataclasses.replace(
            cand, datasheet_url=by_base.get(_base_part(cand.model))
        )
        for cand in candidates
    ]


def _sse_json(text: str) -> dict:
    """Parse an SSE-framed JSON-RPC response: return the object on the ``data:`` line."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    # Some deployments may answer with a plain JSON body.
    return json.loads(text)


def _catalog_url(model: str, feed_url: str | None) -> str | None:
    """Build the human-facing ``microchip.com`` catalog URL from a part's feed URL.

    The microchipdirect ``productUrl`` the MCP returns points at the *store*
    (``microchipdirect.com/product/<part>``), which for RF-MMIC parts renders a
    "This Product is Not Available Online" stub — useless to a user. The real
    catalog page lives at ``www.microchip.com/en-us/product/<slug>`` where
    ``<slug>`` is the very ``<PART>-<TYPE-WORDS>`` slug that names the
    ``parametricData`` feed (e.g. feed ``…/MMA035AA-AMPLIFIER-DISTRIBUTED.json``
    → page ``…/product/MMA035AA-Amplifier-Distributed``).

    The feed slug is upper-cased but the catalog's canonical form title-cases the
    *type words* while the part number keeps its own casing. A part number may
    itself carry a suffix (``ICP0444-FL`` → page ``ICP0444-FL-Power-Amplifier``),
    so we strip the known ``model`` prefix and title-case only the trailing type
    words rather than title-casing blindly (which would break ``FL`` → ``Fl``).
    If the slug doesn't start with ``model`` we leave it verbatim.

    ``www.microchip.com`` is Akamai-blocked to fetchers, but this URL is
    display-only (opened by a human in a browser; never fetched by us), so that
    block is irrelevant. Returns None when there is no feed slug to build from.
    """
    if not feed_url:
        return None
    slug = feed_url.rsplit("/", 1)[-1].removesuffix(".json")
    if not slug:
        return None
    if model and slug.upper().startswith(model.upper() + "-"):
        type_words = slug[len(model) + 1:]
        slug = model + "-" + "-".join(w.capitalize() for w in type_words.split("-"))
    return f"https://www.microchip.com/en-us/product/{slug}"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class MicrochipAdapter(Adapter):
    """Assembles Microchip amplifiers from the MCP API + microchipdirect feeds."""

    manufacturer = "Microchip"
    supported_components = {"amplifier"}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Enumerate amplifier parts, fetch each part's feed, return all Candidates.

        The per-part fetches (physical-specs + feed) run concurrently in a
        bounded thread pool — the MCP tools are documented read-only / stateless
        / PARALLEL-SAFE, and the shared cache provider is thread-safe (distinct
        URLs → distinct files; Microchip has no politeness delay so its fetches
        aren't serialized). No query-side filtering is applied (Microchip exposes
        none via this path); the Verifier applies all constraints (REQ-4.1).
        """
        products = self._enumerate()
        if not products:
            # Tripwire: the MCP enumeration returned nothing for every term
            # → API change / outage.  Fail loudly, don't return empty.
            raise AdapterError(
                manufacturer=self.manufacturer,
                context="MCP search_products returned no parts for any amplifier term",
            )

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            built = pool.map(
                lambda item: self._process_part(item[0], item[1]),
                products.items(),
            )
        return _fill_variant_datasheets([c for c in built if c is not None])

    def _process_part(
        self, model: str, product: dict
    ) -> Candidate | None:
        """One part's fetch chain: physical-specs -> feed -> gated Candidate.

        Fully defensive: any per-part error returns None (skip this part).  This
        runs under ``pool.map``, whose iterator re-raises exceptions — so one bad
        part must never abort the whole manufacturer's result set.
        """
        try:
            physical = self._fetch_physical(model)
            feed_url = physical.get("parametricData")
            if not feed_url:
                return None  # not a parametric RF part
            feed = self._fetch_feed(feed_url)
            if feed is None or not _is_amplifier(feed):
                return None  # fetch failed, or text-search pollution (non-amplifier)
            return self._build_candidate(model, product, physical, feed)
        except Exception:  # noqa: BLE001 — resilience: skip a bad part, never crash the run
            return None

    # ------------------------------------------------------------------
    # Retrieval steps
    # ------------------------------------------------------------------

    def _enumerate(self) -> dict[str, dict]:
        """Union of ``search_products`` over every amplifier term, de-duped by part.

        Per-term failures are tolerated (transient API errors observed); only if
        *every* term fails does the caller's tripwire fire.
        """
        products: dict[str, dict] = {}
        for term in _AMPLIFIER_TERMS:
            offset = 0
            while True:
                try:
                    inner = self._mcp_call(
                        "search_products",
                        {"searchTerm": term, "limit": _SEARCH_LIMIT, "offset": offset},
                    )
                except AdapterError:
                    break  # skip this term; other terms still contribute
                data = inner.get("data") if isinstance(inner, dict) else None
                if not isinstance(data, dict):
                    break
                page = data.get("products") or []
                for prod in page:
                    pn = prod.get("partNumber")
                    if pn:
                        products.setdefault(pn, prod)
                pagination = data.get("pagination") or {}
                offset += len(page)
                if not page or not pagination.get("hasMore"):
                    break
        return products

    def _fetch_physical(self, part_number: str) -> dict:
        """Return the ``search_product_physical_specs`` data for a part ({} on failure).

        The tool returns two shapes depending on how many products the part
        number matches:

        - a **flat** object (``partNumber``, ``parametricData``, …) for a unique
          match (e.g. MMA035AA);
        - a ``{"products": [...]}`` **list** when the part number also matches
          variants — tape-and-reel ``…/TR``, eval boards ``…E`` (e.g. MMA044PP3).
          Here ``parametricData`` is nested one level down, so we pick the row
          whose ``partNumber`` is exactly the one we asked for.

        Handling only the flat shape would silently drop every part that has
        sibling variants (its ``parametricData`` reads as ``None`` → skipped).
        """
        try:
            inner = self._mcp_call(
                "search_product_physical_specs", {"partNumber": part_number}
            )
        except AdapterError:
            return {}
        data = inner.get("data") if isinstance(inner, dict) else None
        if not isinstance(data, dict):
            return {}
        products = data.get("products")
        if isinstance(products, list):
            for prod in products:
                if isinstance(prod, dict) and prod.get("partNumber") == part_number:
                    return prod
            return {}  # multi-match but our exact part isn't among them → skip
        return data

    def _fetch_feed(self, url: str) -> dict | None:
        """GET one microchipdirect parametric feed (cache-first); None on any error."""
        result = http.fetch(self.manufacturer, url, headers=_FEED_HEADERS)
        if result.text is None:
            return None
        try:
            feed = json.loads(result.text)
        except (json.JSONDecodeError, ValueError):
            return None
        return feed if isinstance(feed, dict) else None

    def _mcp_call(self, tool: str, arguments: dict) -> dict:
        """Call one MCP tool (cache-first POST) and return its unwrapped inner JSON.

        Raises AdapterError on transport failure, JSON-RPC error, or an
        unexpected response shape (the site-change tripwire). The POST body feeds
        the cache key, so each distinct call maps to its own file.
        """
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        result = http.fetch(
            self.manufacturer, _MCP_URL, method="POST", json=body, headers=_MCP_HEADERS
        )
        if result.text is None:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"HTTP error calling MCP {tool}",
            )
        try:
            rpc = _sse_json(result.text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"MCP {tool} returned an unparseable body",
                cause=exc,
            ) from exc

        if "error" in rpc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"MCP {tool} returned a JSON-RPC error: {rpc['error']}",
            )
        try:
            text = rpc["result"]["content"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AdapterError(
                manufacturer=self.manufacturer,
                context=f"MCP {tool} response has an unexpected shape",
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Candidate construction (exposed for tests to call directly)
    # ------------------------------------------------------------------

    def _build_candidate(
        self, model: str, product: dict, physical: dict, feed: dict
    ) -> Candidate | None:
        """Build one Candidate from a part's product/physical/feed data.

        Returns None if the feed is not an amplifier or the model is missing.
        """
        if not model or not _is_amplifier(feed):
            return None

        by_key = {_normalize_key(str(k)): v for k, v in feed.items()}
        raw_params: dict[str, RawValue] = {}

        # Frequency range: combine Freq Min/Max (already GHz; "DC" -> 0).
        f_low = _parse_freq(by_key.get(_FREQ_MIN_KEY))
        f_high = _parse_freq(by_key.get(_FREQ_MAX_KEY))
        if f_low is not None and f_high is not None:
            raw_params["freq_range"] = RawValue(value=(f_low, f_high), unit="GHz")

        # Scalar electrical params.
        for key, (canonical, unit) in FEED_MAP.items():
            value = _parse_float(by_key.get(key))
            if value is not None:
                raw_params[canonical] = RawValue(value=value, unit=unit)

        # VDD: from the "Bias" string, else a "Voltage (V)" field.
        vdd = _parse_bias_volts(by_key.get(_BIAS_KEY))
        if vdd is None:
            vdd = _parse_float(by_key.get(_VOLTAGE_KEY))
        if vdd is not None:
            # A bias/supply figure is a single value -> degenerate (v, v) interval,
            # the shape the contains rule compares (never a bare float).
            raw_params["VDD"] = RawValue(value=(vdd, vdd), unit="V")

        # Size / MSL come from the MCP physical-specs (not the feed).
        size = _parse_size_mm(physical.get("packageWidthOrSize"))
        if size is not None:
            raw_params["Size"] = RawValue(value=size, unit="mm")
        msl = _parse_msl(physical.get("msl"))
        if msl is not None:
            raw_params["MSL"] = RawValue(value=msl, unit="")

        # Prefer the microchip.com catalog page (built from the feed slug) over the
        # microchipdirect store URL, which is a "Not Available Online" stub for
        # RF-MMIC parts; fall back to the store URL only if no feed slug is known.
        url = (
            _catalog_url(model, physical.get("parametricData"))
            or product.get("productUrl")
            or f"https://www.microchipdirect.com/product/{model}"
        )

        # Datasheet link: the MCP hands it back directly (``datasheetUrl``) in the
        # already-fetched product / physical-specs payloads — no extra request, no
        # HTML scrape.  This is a "case 1" source: the link rides along with the
        # other parameters through the same allowed MCP channel (api.microchip.com,
        # which serves no robots.txt).  Not every part has one (some are null) →
        # ``datasheet_url`` stays None, which the enrichment stage treats as
        # no-accessible-datasheet.  The PDF itself lives on ww1.microchip.com;
        # carrying the URL is not fetching it (that is the pipeline's concern).
        datasheet_url = product.get("datasheetUrl") or physical.get("datasheetUrl")

        return Candidate(
            model=model,
            manufacturer=self.manufacturer,
            url=url,
            raw_params=raw_params,
            source="table",
            datasheet_url=datasheet_url,
        )
