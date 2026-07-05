# Requirements — Microchip Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to Microchip. The full investigation
> and design rationale are in
> [../../iteration2/microchip-plan.md](../../iteration2/microchip-plan.md).

---

## Assumptions

- **MCHP-A-1** — Microchip's public **MCP server** (`https://api.microchip.com/mcp/resources`,
  no auth, JSON-RPC) stays available and stable enough to enumerate parts and
  return each part's `parametricData` feed URL.
- **MCHP-A-2** — The per-part parametric feed
  (`https://www.microchipdirect.com/feed/json/<slug>.json`) stays open (no
  Akamai block) and keeps its flat electrical-spec schema
  (`Freq Min/Max GHz`, `Gain (dB)`, `NF (dB)`, `OIP3 (dBm)`, `p1db(dBM)`, `Bias`).
- **MCHP-A-3** — `www.microchip.com` is Akamai-blocked to non-browser clients and
  is **not** used by the adapter for any data.

## Open Questions

- **MCHP-OQ-1** — *(resolved)* Enumeration: the 7-term union yields ~118 parts;
  the feed `product_type` key is a clean amplifier discriminator (only RF-MMIC
  feeds carry it). Residual caveat: coverage depends on text search; the
  Akamai-blocked parametric-search category is the only authoritative count.
- **MCHP-OQ-2** — *(resolved)* Power amps publish saturated power as `Pout (dBm)`
  (not "Psat"); mapped to the `Psat` ontology param.
- **MCHP-OQ-3** — *(resolved)* No serial delay; a bounded `ThreadPoolExecutor`
  (`_MAX_WORKERS`=8) caps concurrency (MCP tools are PARALLEL-SAFE). ~25–30 s live.
  SQLite TTL cache (NFR-6) is future work — not yet wired (CLI is a stub).
- **MCHP-OQ-4** — Policy confirmation that sidestepping the unreadable
  (Akamai-403) `www.microchip.com/robots.txt` by never touching that host is
  acceptable.
- **MCHP-OQ-5** — `manufacturer` string / file name (recommend `"Microchip"`,
  `microchip.py`).
- **MCHP-OQ-6** — Temperature (and other datasheet-only params): defer PDF
  parsing, resolve to UNKNOWN for now.
- **MCHP-OQ-7** — `Size` from the `"L x W x H mm"` string uses the **largest
  edge** as the scalar; confirm this matches intended `Size` semantics.

## Definition of Done

- The system returns real amplifier candidates from Microchip, sourced entirely
  from the MCP API + `microchipdirect` feeds, with **no access to
  `www.microchip.com`**.
- Enumeration covers the amplifier sub-types (LNA, power, wideband, gain block,
  distributed, driver…) via term-union + `product_type` gating; the Verifier
  applies all numeric constraints.
- Offline tests pass against trimmed feed fixtures; live tests are marked
  `@pytest.mark.network`.
