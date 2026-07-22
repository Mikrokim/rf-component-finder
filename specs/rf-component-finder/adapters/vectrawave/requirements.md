# Requirements — VectraWave Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to VectraWave.

---

## Context

VectraWave is a GaN/GaAs III-V MMIC house, defense/radar-oriented ("MMIC
Solutions up to 100 GHz"). Most parts are **bare die**. Its amplifier line
covers: High Power (>3W), Medium Power (<3W), Low Noise, Wideband, and Core Chips
(T/R front-end modules). (It also sells attenuators and phase shifters — not
amplifiers.)

## Assumptions

- **VW-A-1** — The parametric data is a single server-rendered HTML page at
  `/search-engine-mmic`, built with the Divi "Table Maker" plugin (rows/cells are
  `div.dvmd_tm_trow` / `div.dvmd_tm_tcell` / `div.dvmd_tm_cdata`). Data is in the
  raw HTML — no JavaScript needed. Accessible via `httpx` (no bot-wall).
- **VW-A-2** — Tables are **transposed**: each product is a **column** and each
  parameter is a **row** (first cell = parameter label, e.g. "FrequencyMin GHZ").
  Product-header rows (part numbers) repeat between parameter rows.
- **VW-A-3** — The page mixes component types under section headings; only the
  five amplifier sections are in scope (see [t8-plan.md](t8-plan.md) §5).
- **VW-A-4** — Each part-number header cell is an `<a href>` to that part's own
  **product page** (`/product/<pn>`). `Candidate.url` is that product-page link
  (display only, never fetched), **not** the Datasheet-row PDF link; a part that
  carries no link falls back to the catalogue page.

## Open Questions

- **VW-OQ-1** — `IP3` and `MSL` are **not published anywhere** by VectraWave
  (verified: absent from the table and from both a PA and an LNA datasheet).
  This is by the nature of the product line (saturated power/radar parts aren't
  characterized for linearity; bare die have no JEDEC MSL), not a data gap. They
  stay UNKNOWN for VectraWave.
- **VW-OQ-2** — "Core Chips" are T/R modules with split Tx/Rx specs
  (`Tx Gain`, `Tx Pout`, `Rx Gain`, `Rx NF`). How to map a dual-path module onto
  the single-amplifier ontology is undecided — may be deferred. See t8-plan §5.
- **VW-OQ-3** — `Temperature` is datasheet-only (operating/storage), `Size` is the
  approximate die/package dimension; both are owned by the datasheet fallback.

## Definition of Done

- The system returns real amplifier candidates from VectraWave (the five amplifier
  sections; attenuators/phase shifters excluded).
