# Microchip Adapter — Investigation & Plan

> Manufacturer-specific plan for **microchip.com** (Microchip Technology, incl.
> legacy Microsemi / Mimix RF-MMIC lines). The generic **Site Adapter**
> requirements (REQ-3) live in
> [../iteration1/requirements.md](../iteration1/requirements.md); the lean
> per-vendor spec is
> [../adapters/microchip/requirements.md](../adapters/microchip/requirements.md).
> This file holds the REQ-3.3 investigation trail, the chosen retrieval method,
> the spec→ontology mapping, risks, and open questions.
>
> Status: **investigation complete, code not yet written.** All findings below
> were established by live probing of Microchip's public endpoints on 2026-07-01
> (and independently reproduced by the user in Postman).

---

## 1. TL;DR — the one thing to remember

**Do not scrape `www.microchip.com` — it is hard-blocked by Akamai** (403 to
`httpx` even with a browser User-Agent, on `robots.txt` *and* every
`/parametric-search/<id>` page). Instead this adapter uses **two open JSON hosts**:

1. **`api.microchip.com/mcp/resources`** — Microchip's public, no-auth **MCP
   server** (JSON-RPC over HTTP). Used to **enumerate** amplifier part numbers and
   to obtain each part's parametric-feed URL + physical specs.
2. **`microchipdirect.com/feed/json/<slug>.json`** — a clean per-part JSON feed
   carrying the **RF electrical specs** (Freq, Gain, NF, OIP3, P1dB, Bias).

Retrieval is a **three-step chain per run**:

```
1. MCP search_products {searchTerm, limit:60, offset}  -> part numbers (paginate, union terms)
2. MCP search_product_physical_specs {partNumber}      -> parametricData URL + Size + MSL
3. GET <parametricData URL>  (microchipdirect feed)    -> Gain / NF / Freq / OIP3 / P1dB / Bias
   -> filter by feed product_type, map JSON to canonical params
```

No Playwright, no HTML scraping, no public-site access. **The electrical
parameters are NEVER in an MCP response directly** — the MCP only hands back the
feed *URL*; the numbers live in the feed at the end of the chain. The Verifier
applies all constraints.

This is a **third retrieval pattern** for the project: a **JSON API** adapter,
alongside macom's embedded-`data-part` JSON and minicircuits/ums's
server-rendered tables.

---

## 2. How Microchip serves product data (investigation findings, REQ-3.3)

Decision rule: *prefer an official API → else a server-side parametric URL → else
scrape.* Each row: finding + consequence.

| Question | Finding (live-verified) | Consequence |
|---|---|---|
| **Official / public API?** | **Yes.** MCP server at `https://api.microchip.com/mcp/resources` — public, **no auth**, JSON-RPC over HTTP (`serverInfo: ProductInfoMcpServer 1.0.0.0`). `tools/call` works stateless (no session handshake required). | **Use REQ-3.3 option 1.** This is the primary source. |
| **Does the API expose RF electrical specs directly?** | **No.** `search_products` returns only catalog data (partNumber, description, datasheetUrl, productUrl, stock, lead time). `search_product_physical_specs` returns package size/MSL + a **`parametricData` URL** — still not the electrical numbers. | The electrical specs need a third hop (the feed). |
| **Where are the electrical specs?** | **A per-part JSON feed** on `www.microchipdirect.com/feed/json/<slug>.json` — HTTP 200, `application/json`, **not blocked**. Flat dict: `Freq Min/Max GHz, Gain (dB), NF (dB), OIP3 (dBm), p1db(dBM), Bias, Package (mm), product_type`. | Parse this feed for the ontology params. |
| **Is the feed URL derivable from the part number?** | **No.** Slug is `<PART>-<TYPE-WORDS>` (e.g. `MMA044AA-LOW-NOISE-AMPLIFIER`); `basePartNumber` alone (e.g. `"AMPLIFIER"` for `UATM30S2C`) 404s. Some catalog parts have `parametricData: null`. | **Must** read `parametricData` from MCP physical-specs; never construct the URL. |
| **Server-side parametric URL filter (option 2)?** | **Exists but unusable.** `www.microchip.com/en-us/parametric-search/<id>` (e.g. `1272` = Power Amplifiers) is the authoritative category tool, but the host is Akamai-blocked (see §3). | Cannot use option 2. |
| **Scrape the public site (option 3)?** | **Blocked.** `www.microchip.com` returns `403 Access Denied` (`errors.edgesuite.net` = Akamai Bot Manager) to `httpx` even with a full browser UA. | Reject option 3. Avoid `www.microchip.com` entirely. |
| **Enumeration source** | MCP `search_products` is **text search**, not a category browse, and is **polluted**: `"amplifier"` (46 hits) returns op-amps (`MCP664`), HV drivers (`HV56020`), SerDes limiting amps (`SY88349`). | Enumerate by a **union of amplifier terms**, then **confirm each via feed `product_type`**. See §6 + OQ-1. |
| **Rows / counts** | Per-term totals (overlapping): amplifier 46, MMIC 50, low-noise-amplifier 36, power-amplifier 27, gain-block 20, LNA 21. True RF-amplifier count after `product_type` filtering: **TBD** (OQ-1). | Union + dedupe + product_type filter; expect low hundreds of parts. |

**Why not the human-facing parametric tables?** They are the authoritative, clean
category lists — but they live on the Akamai-blocked host and cannot be fetched
programmatically without a full headless browser (fragile). The MCP API + feed
give the same electrical data through supported, unblocked JSON endpoints.

---

## 3. Compliance & access

- **`www.microchip.com/robots.txt` is unreadable** — the host 403s all
  non-browser access, so robots directives cannot be fetched. We therefore **do
  not touch `www.microchip.com`** at all. (OQ-4)
- **`api.microchip.com` (MCP server)** is explicitly **public, no-auth**, and
  purpose-built for programmatic agents ("copilots, AI chatbots, LLM-based IDEs,
  enterprise AI agents"). Using it for a product-search retriever is in-policy.
- **`microchipdirect.com` feeds** return clean JSON to a browser UA. Its HTML /
  sitemap endpoints are flaky/blocked, but `/feed/json/<slug>.json` is reliable —
  we use only that.
- **Identity:** send an honest browser-style User-Agent and the MCP protocol
  headers (`Content-Type: application/json`, `Accept: application/json,
  text/event-stream`). No impersonation of a named bot.
- **Politeness:** self-imposed delay between MCP calls and feed fetches
  (recommend 1–3 s; no readable Crawl-delay). SQLite/TTL cache serves repeats
  (NFR-6).

---

## 4. The retrieval recipe (what `search()` will do)

```
_MCP_URL    = "https://api.microchip.com/mcp/resources"
_FEED_HOST  = "https://www.microchipdirect.com"      # feed URLs come from MCP, never built
_USER_AGENT = "Mozilla/5.0 … Chrome/124 … Safari/537.36"
_AMPLIFIER_TERMS = ("low noise amplifier","power amplifier","distributed amplifier",
                    "driver amplifier","gain block","wideband amplifier","MMIC amplifier", …)
_MAX_WORKERS = 8   # per-part fetches fan out concurrently (OQ-3)
```

1. **MCP call helper:** POST `tools/call` with
   `{"name": <tool>, "arguments": {…}}`. Works stateless (no init handshake
   needed). Response is **SSE-framed** — parse the line starting `data:`; the
   payload is a JSON *string* under `result.content[0].text` (double-encoded).
2. **Enumerate:** for each term in `_AMPLIFIER_TERMS`, call
   `search_products {searchTerm, limit:60, offset}`; paginate on
   `pagination.hasMore` (offset += 60). Collect `partNumber`s into a set.
3. **Per part (concurrent):** call `search_product_physical_specs {partNumber}`
   → read `parametricData` (feed URL), `packageWidthOrSize` (Size), `msl`.
   - If `parametricData` is null → skip (not a parametric RF part).
4. **Fetch feed:** GET `parametricData` (browser UA) → `response.json()`.
5. **product_type gate:** keep only feeds whose `product_type` names an amplifier
   (LNA / amplifier / gain block / …); drop the text-search pollution.
6. **Concurrency, not serial delay:** the ~118 per-part chains (physical-specs +
   feed) run in a bounded `ThreadPoolExecutor` (`_MAX_WORKERS`, default 8). The
   MCP tools are documented read-only / stateless / **PARALLEL-SAFE**, and
   `httpx.Client` is thread-safe, so the worker cap replaces a per-request sleep —
   fast *and* polite. This drops a live run from ~4–6 min (serial + 1 s delay) to
   **~25–30 s** (measured).
7. **Errors:** per-part failures return `None` and are skipped (one bad part must
   not kill the run); MCP transport/shape errors raise
   `AdapterError(manufacturer, context, cause)`; if enumeration yields **zero**
   parts across all terms → raise (site-change tripwire).

**Caching (NFR-6):** enumeration + per-part fetches are all read-only; a SQLite
TTL cache (7 days) keyed by request would serve repeats instantly. Caching is a
system-level concern (the CLI entry point is still a stub) and is **not yet wired
in** — every run currently pays the ~25–30 s live cost. Future work.

---

## 5. The parsing recipe (feed JSON → params)

The feed is a flat JSON dict. Parse rules:

- **Frequency:** combine `Freq Min GHz` + `Freq Max GHz` → `freq_range`, unit
  `GHz` (already GHz — no MHz conversion, like UMS). **`"DC"` → `0.0`** (Mini-
  Circuits-style band edge). Emit only when both edges parse.
- **Scalars (name-based, normalized keys):** `Gain (dB)`→Gain, `NF (dB)`→NF,
  `OIP3 (dBm)`→IP3, `p1db(dBM)`→P1dB (mind the odd casing).
- **Bias → VDD:** `Bias` is a string like `"4V,102mA"` / `"4V, 80mA"`; parse the
  leading voltage number → VDD (V).
- **Size:** from MCP `packageWidthOrSize` (e.g. `"1.351 x 1.121 x 0.1 mm"`); the
  feed's `Package (mm)` is often just `"Die"` (a form, not a size).
- **MSL:** from MCP `physicalSpecs.msl` / `compliance.msl` (often null → omit).
- **Missing / non-numeric** → omit the param → Verifier marks UNKNOWN (never FAIL).
- **Tripwire (fail loudly):** if enumeration returns **zero** parts, or the MCP
  response shape changes, raise `AdapterError` — never return empty silently.

### Candidate construction (architecture fit — same contract as the others)
- `model` = part number; `url` = `productUrl` (microchipdirect product page),
  display-only, never fetched; `source = "table"`.
- **No query-side filtering** — return every amplifier; the Verifier filters.
- **`@register`**, `manufacturer = "Microchip"`, `supported_components = {"amplifier"}`.

---

## 6. Spec → canonical ontology mapping (REQ-3.4)

Targets the amplifier ontology
([../../rf_finder/ontology/parameters.py](../../../rf_finder/ontology/parameters.py)).
Name-based (robust to key reordering / new fields):

```python
FEED_MAP = {                      # normalized feed key -> (canonical, unit)
    "gain db":  ("Gain", "dB"),
    "nf db":    ("NF",   "dB"),
    "oip3 dbm": ("IP3",  "dBm"),
    "p1db dbm": ("P1dB", "dBm"),
}
# freq_range  <- Freq Min GHz / Freq Max GHz (GHz; "DC"->0)
# VDD         <- Bias (parse leading volts), else "Voltage (V)"
# Size        <- MCP packageWidthOrSize (largest edge, mm — OQ-7)
# MSL         <- MCP msl ("MSL-n" -> n)
# Psat        <- feed "Pout (dBm)"  (RESOLVED OQ-2: power amps use Pout, not Psat)
# Temperature <- datasheet only -> UNKNOWN (deferred, cf. UMS OQ-U4)
```

Expected coverage: `freq_range`, `Gain` near-universal; `NF` on LNAs/wideband;
`IP3`, `P1dB` common; `VDD` from Bias; `Size`/`MSL` from MCP; `Psat` on power amps
(pending OQ-2); `Temperature` deferred. Exact %s → after the OQ-1 census.

---

## 7. Gotchas & risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **`www.microchip.com` Akamai-blocked** (403 even w/ browser UA). | Never fetch it. Use MCP API + microchipdirect feed only. |
| R2 | **Text-search pollution** — op-amps/HV/SerDes returned for "amplifier". | Gate on feed `product_type`; curated term union (OQ-1). |
| R3 | **Feed URL not derivable** from part number; some parts have none. | Always read `parametricData` from MCP; skip nulls. |
| R4 | **MCP responses are SSE-framed** JSON-RPC, double-encoded payload. | Parse the `data:` line → `result.content[0].text` → `json.loads`. |
| R5 | **`Bias` is a compound string**; `Freq` may be `"DC"`. | Dedicated parsers: leading-volts for Bias, `"DC"`→0 for freq. |
| R6 | **Enumeration completeness unknown** (text search, not category). | Union of terms + product_type filter; parametric-search category = manual audit only (OQ-1). |
| R7 | **microchipdirect HTML/sitemap flaky**; only the JSON feed is reliable. | Use only `/feed/json/<slug>.json`; wrap errors in AdapterError. |
| R8 | **Three hops** (search → physical_specs → feed) × ~118 parts = many requests. | Fan out per-part chains with a bounded thread pool (`_MAX_WORKERS`=8; MCP tools are PARALLEL-SAFE) → ~25–30 s. SQLite TTL cache is future work (not yet wired). |
| R9 | **MCP is a young service** (v1.0) — schema/availability may change. | Fail-loud tripwire on shape change; name-based maps. |

---

## 8. Open questions

- **OQ-1 — Enumeration completeness & term set.** *Resolved by census:* the term
  union (7 terms) yields ~118 distinct parts; the **only** feeds carrying a
  `product_type` key are the RF-MMIC ones, so the gate (`product_type` present AND
  matches `amplif`/`lna`) is a clean discriminator (op-amps/PGAs/MCUs have no
  `product_type`). ~29 RF amps in a 70-part sample. Residual caveat: coverage
  still depends on text search surfacing the parts; the Akamai-blocked
  parametric-search category remains the only authoritative count (manual audit).
- **OQ-2 — Psat field name.** *Resolved:* power amplifiers publish saturated power
  as **`Pout (dBm)`** (not "Psat"); mapped to the `Psat` ontology param. LNAs /
  wideband parts omit it.
- **OQ-3 — Politeness under concurrency.** *Resolved:* no serial delay; instead a
  bounded `ThreadPoolExecutor` (`_MAX_WORKERS`=8) caps in-flight requests (MCP
  tools are PARALLEL-SAFE). Live run ~25–30 s. Surface the worker cap in config
  when the loader lands; add a SQLite TTL cache later (NFR-6).
- **OQ-4 — robots.txt unreadable** (host 403s it). We sidestep by never touching
  `www.microchip.com`; confirm this is acceptable policy.
- **OQ-5 — `manufacturer` string / file name.** Recommend `"Microchip"`,
  `rf_finder/adapters/microchip.py`.
- **OQ-6 — Temperature / datasheet params.** Defer PDF parsing (like UMS OQ-U4);
  resolve Temperature to UNKNOWN for now.
- **OQ-7 — `Size` interpretation.** The source is a 3-D `"L x W x H mm"` string but
  the ontology `Size` is a single `max` scalar. *Applied:* use the **largest edge**
  ("fits within X mm"). Confirm this matches the intended `Size` semantics.

---

## 9. Definition of Done

- The adapter returns real amplifier candidates from Microchip, sourced entirely
  from `api.microchip.com` (MCP) + `microchipdirect.com` feeds — **no access to
  `www.microchip.com`**.
- Enumeration covers the amplifier sub-types (LNA, power, wideband, gain block,
  distributed, driver…) via term-union + `product_type` gating.
- Offline tests pass against trimmed fixtures (LNA, wideband, power amp, null-spec
  row, no-results tripwire); live tests marked `@pytest.mark.network`.
- A vendor skill documents this JSON-API retrieval pattern.

---

## 10. Work plan (execution order)

1. **This doc + [../adapters/microchip/requirements.md](../adapters/microchip/requirements.md)**
   — investigation + spec (done).
2. **Bounded enumeration probe** — resolve OQ-1 / OQ-2 (throttled, ~20–30 reqs).
3. **Implement** `rf_finder/adapters/microchip.py` (MCP call helper + SSE parse,
   enumerate, feed fetch/parse, `FEED_MAP`, Bias/DC parsers, rate guard,
   tripwires, `@register`).
4. **Tests + fixtures** `tests/adapters/test_microchip.py` (offline; live behind
   `@pytest.mark.network`).
5. **Vendor skill** via
   [adapter-skill-writer](../../../.claude/skills/adapter-skill-writer/SKILL.md).

---

## 11. File map (planned)

| File | Role |
|---|---|
| [../adapters/microchip/requirements.md](../adapters/microchip/requirements.md) | Lean per-vendor spec (assumptions / OQs / DoD). |
| `rf_finder/adapters/microchip.py` | The adapter (to be written). |
| [../../../rf_finder/adapters/base.py](../../../rf_finder/adapters/base.py) | `Adapter` ABC, `AdapterError`, `@register`. |
| [../../../rf_finder/models.py](../../../rf_finder/models.py) | `Candidate`, `RawValue`, `QuerySpec`. |
| [../../../rf_finder/ontology/parameters.py](../../../rf_finder/ontology/parameters.py) | Canonical amplifier params/units. |
| `tests/adapters/test_microchip.py` | Offline unit tests (to be written). |
| `tests/fixtures/microchip_*.json` | Trimmed feed fixtures (to be written). |
| this file | Investigation & plan. |
