---
name: microchip
description: >-
  Complete retrieval guide for microchip.com (Microchip Technology, incl. legacy
  Microsemi / Mimix RF-MMIC lines). Use whenever you work on the Microchip adapter
  (rf_finder/adapters/microchip.py) — to understand how the site serves product
  data, to debug or maintain the amplifier adapter, or (the main forward-looking
  use) to ADD A NEW COMPONENT TYPE (mixer, switch, attenuator, …) to the Microchip
  adapter beyond amplifiers. Covers the official-API retrieval method (the MCP
  server + microchipdirect JSON feed, since www.microchip.com is Akamai-blocked),
  the three-hop chain, the product_type gate, concurrency, parsing gotchas
  (SSE-framed JSON-RPC, Bias string, "DC" freq, Pout=Psat), the feed→ontology
  mapping, what was already built, and a step-by-step expansion recipe.
---

# Microchip (microchip.com) — Component Retrieval Skill

This skill is the **operating manual for retrieving RF/microwave product data from
Microchip** (Microchip Technology, including the legacy Microsemi / Mimix MMIC
lines). It records how the site behaves, how the existing **amplifier** adapter
was built, and how to extend it to **new component types**. If you are touching
`rf_finder/adapters/microchip.py` or adding a category, read this first — you
should not have to re-investigate the site from scratch.

> Reference implementation: [microchip.py](../../../rf_finder/adapters/microchip.py)
> Original investigation: [microchip-plan.md](../../../specs/rf-component-finder/iteration2/microchip-plan.md) · per-vendor spec: [requirements.md](../../../specs/rf-component-finder/adapters/microchip/requirements.md)
> Architecture contracts: [base.py](../../../rf_finder/adapters/base.py), [models.py](../../../rf_finder/models.py)
> Contrast with the other JSON-API site: [analogdevices](../../../rf_finder/adapters/analogdevices.py) (one endpoint, all specs inline) · embedded-JSON: [macom skill](../macom/SKILL.md) · server-rendered tables: [minicircuits skill](../minicircuits/SKILL.md) · [ums skill](../ums/SKILL.md) · [threerwave skill](../threerwave/SKILL.md)

---

## 1. TL;DR — the one thing to remember

**Never touch `www.microchip.com` for data — it is hard-blocked by Akamai** (403
even to a browser-UA `httpx`, on `robots.txt` *and* every `/parametric-search/<id>`
page). The parametric tables you see in a browser cannot be fetched
programmatically. Instead the adapter assembles data from **two open JSON hosts**
in a **three-hop chain**:

```
1. MCP search_products              (api.microchip.com)  -> enumerate part numbers
2. MCP search_product_physical_specs(api.microchip.com)  -> per part: parametricData feed URL + Size + MSL
3. GET <parametricData>             (microchipdirect.com) -> RF electrical specs
   -> gate by feed product_type, map JSON -> ontology
```

The **electrical specs are never in an MCP response directly** — the MCP only
hands back the feed *URL*; the numbers (Freq, Gain, NF, OIP3, P1dB, Pout, Bias)
live in the microchipdirect feed at the end of the chain. Plain `httpx` + JSON;
no Playwright, no HTML scraping. The Verifier applies all constraints.

This is a **JSON-API** retrieval pattern (like [analogdevices](../../../rf_finder/adapters/analogdevices.py)),
but multi-hop and enumeration-driven rather than one-shot.

---

## 1b. Datasheet link — where it lives (verified live 2026-07-20)

**Case 1 — the link comes back from the MCP `search()` already calls.**

`datasheetUrl` is returned directly by the MCP — both in `search_products`' `product` dict
and in `search_product_physical_specs`' `physical` — absolute, e.g.
`https://ww1.microchip.com/downloads/…/MMA044AA-…-DS00004231B.pdf`. No extra request, no
HTML scrape. Coverage ~87%. The microchipdirect feed (hop 3) has NO datasheet field.
**Implemented:** `_build_candidate` reads
`product.get("datasheetUrl") or physical.get("datasheetUrl")`.

- **Compliance nuance:** the LINK comes from `api.microchip.com`, which serves no robots.txt
  (public, no-auth, agent-built) — pulling it is unambiguously allowed. The FILE lives on
  `ww1.microchip.com`, whose robots is `User-agent: * / Disallow: /`. Carrying a URL and
  fetching it are different acts; the adapter supplies it (decided with the user), and the
  pipeline's later *fetch* of ww1 is a separate decision.
- **Clean alternative if that fetch is ever disallowed:** the MCP tool
  `search_microchip_product_documents` returns datasheet *content* (markdown, per page)
  straight from `api.microchip.com`, sidestepping ww1 entirely.

---

## 2. How Microchip serves product data (investigation findings, REQ-3.3)

Decision rule (*official API → parametric URL → scrape*), all live-verified:

| Question | Finding | Consequence |
|---|---|---|
| **Official / public API?** | **Yes.** MCP server at `https://api.microchip.com/mcp/resources` — public, **no auth**, JSON-RPC over HTTP (`serverInfo: ProductInfoMcpServer`). `tools/call` works **stateless** (no initialize handshake). | REQ-3.3 option 1. Primary source. |
| **Electrical specs in the API?** | **No, indirectly.** `search_products` = catalog only (partNumber, description, productUrl, stock). `search_product_physical_specs` = package size/MSL + a **`parametricData` URL**. | Need a 3rd hop for the numbers. |
| **Where are the specs?** | **Per-part JSON feed** at `www.microchipdirect.com/feed/json/<slug>.json` — 200, `application/json`, **not blocked**. Flat dict: `Freq Min/Max GHz, Gain (dB), NF (dB), OIP3 (dBm), p1db(dBM), Bias / Voltage (V), Pout (dBm), product_type`. | Parse this feed. |
| **Feed URL derivable?** | **No.** Slug is `<PART>-<TYPE-WORDS>` (e.g. `MMA044AA-LOW-NOISE-AMPLIFIER`); `basePartNumber` alone (`"AMPLIFIER"` for UAT parts) 404s. Some parts have `parametricData: null`. | Always read `parametricData` from the MCP; never build it. Skip nulls. |
| **Parametric URL (option 2)?** | Exists (`/parametric-search/<id>`, e.g. `1272`=Power Amps, `1421`=MMIC LNAs) but on the **Akamai-blocked host**. | Unusable programmatically. |
| **Scrape (option 3)?** | **403** (`errors.edgesuite.net` = Akamai) even with a browser UA. | Rejected. Avoid `www.microchip.com` entirely. |
| **Enumeration** | `search_products` is **text search**, polluted: `"amplifier"` returns op-amps (`MCP664`), HV drivers (`HV56020`), SerDes (`SY88349`). | Union curated amplifier terms; **gate by feed `product_type`** (§5). |

This differs from analogdevices (one endpoint returns the whole dataset with
specs inline). Microchip needs **enumerate → per-part feed**, so it makes many
requests — hence the concurrency in §4.

---

## 3. Compliance & access

- **`www.microchip.com/robots.txt` is unreadable** (host 403s all non-browser
  access), so we cannot fetch robots directives. We sidestep this by **never
  touching `www.microchip.com`** (microchip-plan OQ-4).
- **`api.microchip.com` (MCP)** is explicitly **public, no-auth**, and built for
  programmatic agents ("copilots, AI chatbots, LLM-based IDEs, enterprise AI
  agents") — using it for a product-search retriever is in-policy.
- **`microchipdirect.com` feeds** return clean JSON to a browser UA. Its HTML /
  sitemap endpoints are flaky/blocked; only `/feed/json/<slug>.json` is reliable.
- **Identity:** honest browser-style User-Agent + MCP headers
  (`Content-Type: application/json`, `Accept: application/json, text/event-stream`).
- **Politeness:** no readable Crawl-delay → **bounded concurrency** (a worker cap)
  instead of a serial delay (§4). A SQLite/TTL cache (NFR-6) is future work.

---

## 4. The retrieval recipe (what `search()` does)

```python
_MCP_URL   = "https://api.microchip.com/mcp/resources"
# feed URLs come from each part's parametricData; NEVER built by hand.
_USER_AGENT = "Mozilla/5.0 … Chrome/124 … Safari/537.36"
_MCP_HEADERS  = {UA, "Content-Type": application/json,
                 "Accept": "application/json, text/event-stream"}
_AMPLIFIER_TERMS = ("low noise amplifier","power amplifier","distributed amplifier",
                    "driver amplifier","wideband amplifier","gain block","MMIC amplifier")
_SEARCH_LIMIT = 60      # MCP max page size
_MAX_WORKERS  = 8       # concurrency cap for per-part fetches
```

1. **Enumerate** (`_enumerate`): for each term, `search_products
   {searchTerm, limit:60, offset}`, paginate on `pagination.hasMore` (offset+=len).
   Collect `partNumber`s into a dict (dedupe across terms). **Per-term failures are
   tolerated** (e.g. the term `"driver amplifier"` deterministically returns a
   no-`data` shape); only if *every* term yields nothing does the tripwire fire.
2. **Per part, concurrently** (`ThreadPoolExecutor(_MAX_WORKERS)` over
   `products.items()`; `httpx.Client` is thread-safe, MCP tools are PARALLEL-SAFE):
   `_process_part` runs the chain and returns a `Candidate` or `None`.
3. `search_product_physical_specs {partNumber}` → `parametricData`,
   `packageWidthOrSize`, `msl`. Null `parametricData` → skip.
4. **GET the feed** → `response.json()`.
5. **product_type gate** (`_is_amplifier`, §5) → drop pollution.
6. `_build_candidate` (§6).

**Why concurrency, not a serial delay:** ~118 parts × (physical + feed) is many
requests; serial + a 1 s sleep took **4–6 min**. A bounded thread pool drops a
live run to **~25–30 s** with no correctness change (microchip-plan §4/OQ-3).

**MCP transport (`_mcp_call`):** POST `tools/call`; the response is
**SSE-framed** — the JSON-RPC object is on the line starting `data:`, and the
tool payload is a JSON *string* under `result.content[0].text` (double-encoded).
`_sse_json` extracts the `data:` line; then `json.loads(rpc["result"]["content"][0]["text"])`.

**Errors:** `_fetch_physical`/`_fetch_feed` swallow their errors (return `{}` /
`None` → skip that part). `_process_part` is wrapped in a blanket `try/except →
None` so **one bad part never aborts the whole run** (it executes under
`pool.map`, whose iterator re-raises). `_mcp_call` raises
`AdapterError(manufacturer, context, cause)` on transport / JSON-RPC / shape
errors. If enumeration returns **zero** parts across all terms → raise
`AdapterError` (the site-change tripwire; never return empty silently).

---

## 5. The product_type gate (`_is_amplifier`)

The single most important filter. `search_products` text search is polluted, so
each feed is gated:

```python
_AMPLIFIER_TYPE_MARKERS = ("amplif", "lna", "gain block")
# keep iff feed has a str product_type AND its lowercase contains a marker
```

Two things make this robust:
- **Only RF-MMIC feeds carry a `product_type` key at all.** Op-amp / PGA / MCU
  feeds have entirely different schemas (`Aol (dB)`, `Slew Rate`, `Flash Size`, …)
  and **no** `product_type`, so a missing key already rejects them.
- The marker is **`"amplif"`, not `"amplifier"`**, because a real value is
  misspelled: `"Distributed Power-Amplifer (Driver)"` (sic). Observed amplifier
  types: `Power Amplifier`, `Distributed Low Noise Amplifier`, `Distributed
  Amplifier`, `Wideband Low Noise Amplifier`, `Wideband Amplifier`, `Low Noise
  Amplifier` (and casing variants).

---

## 6. From a feed to a `Candidate` (`_build_candidate`)

Feed keys are normalised (`_normalize_key`: lowercase; drop `()+/\.,:±%-`;
collapse spaces) so `"p1db(dBM)"` → `p1db dbm`, `"Freq Min GHz"` → `freq min ghz`.

| Source | Use |
|---|---|
| MCP `partNumber` | `Candidate.model` (skip if missing) |
| MCP `productUrl` | `Candidate.url` (microchipdirect product page; **display-only, never fetched**); fallback `…/product/<model>` |
| feed `Freq Min/Max GHz` | `freq_range` (GHz; **`"DC"` → 0.0**, emit only if both edges parse) |
| feed scalars via `FEED_MAP` | `raw_params` (§7) |
| feed `Bias` / `Voltage (V)` | `VDD` — parse leading volts from `Bias` (e.g. `"4V, 80mA"` → 4.0), else `Voltage (V)` directly |
| MCP `packageWidthOrSize` | `Size` — **largest edge in mm** from `"L x W x H mm"` (OQ-7) |
| MCP `msl` | `MSL` — digits from `"MSL-n"`; usually null → omit |

Missing / non-numeric / sentinel → param omitted → Verifier marks UNKNOWN
(partial), never FAIL. `source = "table"`.

### Architecture fit (same contract as the others)
- **No query-side filtering** — return every amplifier; the **Verifier** applies
  all constraints (REQ-4.1). `search(spec)` ignores `spec` (like the other adapters).
- **Self-registers** via `@register`; `manufacturer = "Microchip"`,
  `supported_components = {"amplifier"}`. Must be imported in
  [__main__.py](../../../rf_finder/__main__.py) to trigger registration.

---

## 7. Feed → canonical ontology mapping (REQ-3.4)

Name-based, keyed by the **normalised** feed key:

```python
FEED_MAP = {                       # normalised feed key -> (canonical, unit)
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "oip3 dbm": ("IP3",  "dBm"),   # OUTPUT IP3; IIP3 (input) is intentionally ignored
    "p1db dbm": ("P1dB", "dBm"),
    "pout dbm": ("Psat", "dBm"),   # power amps publish saturated power as "Pout (dBm)"
}
# freq_range <- Freq Min/Max GHz (GHz; already canonical — no conversion)
# VDD        <- Bias (leading volts) or "Voltage (V)"
# Size       <- MCP packageWidthOrSize (largest edge, mm)
# MSL        <- MCP msl
# Temperature-> datasheet only -> UNKNOWN (deferred, cf. UMS OQ-U4)
```

Notes:
- **Frequency is already GHz** (the ontology canonical) — unlike MACOM /
  Mini-Circuits (MHz). No conversion; just handle the `"DC"` band edge → 0.
- **`Pout (dBm)` → `Psat`** (RESOLVED OQ-2): power amps do **not** use a "Psat"
  key; they publish `Pout (dBm)`.
- **Distrust nothing exotic:** the feed units are consistent (dB / dBm / GHz),
  unlike MACOM's noisy `uom`.

---

## 8. Gotchas & risks (carry these into any new category)

| # | Risk | Mitigation (applied) |
|---|---|---|
| R1 | **`www.microchip.com` Akamai-blocked** (403 even w/ browser UA). | Never fetch it. MCP API + microchipdirect feed only. |
| R2 | **Text-search pollution** (op-amps / HV / SerDes for "amplifier"). | `product_type` gate (§5); curated term union. |
| R3 | **Feed URL not derivable**; some parts have `parametricData: null`. | Always read it from MCP physical-specs; skip nulls. |
| R4 | **MCP responses are SSE-framed** JSON-RPC, double-encoded payload. | `_sse_json` → `result.content[0].text` → `json.loads`. |
| R5 | **`Bias` compound string**; `Freq` may be `"DC"`; power amps use `Voltage (V)`. | Dedicated parsers: leading-volts, `"DC"`→0, `Voltage (V)` fallback. |
| R6 | **Enumeration completeness** depends on text search (not a category). | Term union + `product_type` gate; the Akamai-blocked parametric category is the only authoritative count (manual audit). |
| R7 | **A whole term can return no data** (e.g. `"driver amplifier"`). | `_enumerate` tolerates per-term failure; tripwire only if **all** terms yield nothing. |
| R8 | **Many requests** (3 hops × ~118 parts). | Bounded `ThreadPoolExecutor` (`_MAX_WORKERS`=8); ~25–30 s. Cache = future work. |
| R9 | **`pool.map` re-raises** — one bad part could nuke all results. | `_process_part` is a blanket `try/except → None`; parsers never raise (e.g. `_parse_size_mm` skips malformed tokens). |
| R10 | **MCP is a young service** (v1.0) — schema/availability may drift. | Fail-loud tripwire on shape change; name-based maps. |
| R11 | **`product_type` misspelling** `"Amplifer"`. | Marker is `"amplif"`, not `"amplifier"`. |

---

## 9. Open questions (status at time of writing)

Tracked in [microchip-plan.md §8](../../../specs/rf-component-finder/iteration2/microchip-plan.md)
and [requirements.md](../../../specs/rf-component-finder/adapters/microchip/requirements.md):

- **OQ-1 — Enumeration completeness.** *Resolved:* term union (7 terms) + the
  `product_type` gate; residual caveat is text-search coverage vs the blocked
  authoritative category.
- **OQ-2 — Psat field name.** *Resolved:* `Pout (dBm)`.
- **OQ-3 — Politeness under concurrency.** *Resolved:* worker cap, no serial delay;
  SQLite TTL cache (NFR-6) still to wire in.
- **OQ-4 — robots.txt unreadable.** Sidestepped by never touching the blocked host;
  confirm policy.
- **OQ-5 — `manufacturer` / file name.** `"Microchip"`, `microchip.py`.
- **OQ-6 — Temperature / datasheet params.** Deferred → UNKNOWN.
- **OQ-7 — `Size` interpretation.** Largest package edge as the `max` scalar; confirm.

---

## 10. EXPANSION GUIDE — adding a new component type to Microchip

The current adapter handles **amplifiers only**. The retrieval/parse machinery
(§4–§6) is **category-agnostic** — the per-category work is the search terms, the
`product_type` markers, and the spec map.

1. **Register the component type** in
   [components.py](../../../rf_finder/ontology/components.py) `COMPONENTS` + its
   canonical params/units in
   [parameters.py](../../../rf_finder/ontology/parameters.py). `FEED_MAP` units
   must match.

2. **Find the category's search terms.** There is **no category browse** — you
   enumerate by text. Pick terms that surface the line (e.g. mixer → `"mixer"`,
   `"upconverter"`, `"downconverter"`; switch → `"switch"`, `"SPDT"`, `"SP4T"`).
   Expect pollution; the `product_type` gate is what makes it correct.

3. **Verify the data source is the same.** For a few parts, call
   `search_product_physical_specs` and confirm `parametricData` points at a
   `microchipdirect.com/feed/json/<slug>.json` feed **with a `product_type` key**.
   If a category is served differently (no feed / different host), re-run the
   REQ-3.3 investigation for it and record findings here.

4. **Collect the category's feed keys + `product_type` values** across its parts
   (a small throttled census). Note that key-sets differ (e.g. switches carry
   `Insertion Loss`, `Isolation`; not `Gain`/`NF`).

5. **Build a category-specific map + markers.** Normalised feed key →
   `(canonical, unit)`; a `_TYPE_MARKERS` set for the gate (e.g. `("mixer",)`,
   `("switch",)`), mindful of misspellings/casing.

6. **Parameterize, don't fork.** Promote `_AMPLIFIER_TERMS` / `FEED_MAP` /
   `_AMPLIFIER_TYPE_MARKERS` to a per-component table keyed by `spec.component_type`
   (e.g. `CATEGORIES = {"amplifier": (TERMS, FEED_MAP, MARKERS), "mixer": (…)}`),
   and select by `spec.component_type` in `search`. Keep the thread pool, the
   SSE/`_mcp_call` plumbing, and the fail-loud tripwire.

7. **Carry the gotchas (§8) forward** — never touch `www.microchip.com`,
   `product_type` gate, `parametricData` (never build the URL), SSE parsing,
   defensive `_process_part`, return-all + Verifier-filters, display-only `url`.

8. **Test offline** with a **trimmed** feed fixture per shape (a full-spec part, a
   missing-param part, a `parametricData:null`/no-feed part, a
   no-`product_type`/wrong-type part for the gate), asserting against
   `_build_candidate` directly. Mark live tests `@pytest.mark.network`.

9. **Update this skill** with the new category's terms, markers, map, and quirks.

---

## 11. File map

| File | Role |
|---|---|
| [rf_finder/adapters/microchip.py](../../../rf_finder/adapters/microchip.py) | The adapter (reference implementation). |
| [rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register` / `ADAPTERS`. |
| [rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`. |
| [rf_finder/ontology/parameters.py](../../../rf_finder/ontology/parameters.py) | Canonical amplifier params/units the map targets. |
| [rf_finder/__main__.py](../../../rf_finder/__main__.py) | Imports the adapter to trigger `@register`. |
| [tests/adapters/test_microchip.py](../../../tests/adapters/test_microchip.py) | Offline unit tests. |
| [tests/fixtures/microchip_amplifiers.json](../../../tests/fixtures/microchip_amplifiers.json) | Trimmed feed fixtures (LNA, wideband/DC, power amp, Pout schema, gate-reject cases). |
| [specs/.../iteration2/microchip-plan.md](../../../specs/rf-component-finder/iteration2/microchip-plan.md) | Investigation & plan. |
| [specs/.../adapters/microchip/requirements.md](../../../specs/rf-component-finder/adapters/microchip/requirements.md) | Per-vendor spec. |
