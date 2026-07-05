# Requirements — Qorvo Adapter

> Manufacturer-specific spec. The generic **Site Adapter** requirements (REQ-3)
> and all general behavior live in
> [../../iteration1/requirements.md](../../iteration1/requirements.md).
> This file holds **only** what is unique to Qorvo.
> Implementation plan: [t8-plan.md](t8-plan.md).

---

## Assumptions

- **QRV-A-1** — The full product catalog is served as a single **server-rendered**
  HTML page at `/products/product-list/` (**no query string** — the parametric
  `?categoryID=…` form and `/api` are robots.txt-disallowed via `Disallow: /*?*`
  and `Disallow: /api`). The page (~5.3 MB) holds 77 category blocks
  (`div.pst` → `h3.pst-header-title` → `table.pst-table`); all rows are in the raw
  HTML (no JavaScript needed).
- **QRV-A-2** — The adapter keeps only the **12 amplifier categories** (by `h3`
  title): CATV Amplifiers, CATV Hybrid Amplifiers, Digital Variable Gain
  Amplifiers, Distributed Amplifiers, Driver Amplifiers, Gain Block Amplifiers,
  High Frequency Amplifiers, Low Noise Amplifiers, Low Noise Amplifiers with
  Bypass, Low Phase Noise Amplifiers, Power Amplifiers, Spatium Amplifiers
  (~435 parts). Wi-Fi PA / Infrastructure PA **modules** and RF PA **bias
  controllers** are excluded (different schema / not amplifiers).
- **QRV-A-3** — Columns are mapped by header **title** (`div.pst-col-header-title`)
  with the unit read per-column from `div.pst-col-header-subtitle`. On-page
  params: Frequency Min/Max (**GHz or MHz** — varies by category), Gain, OP1dB
  (→P1dB), OIP3 (→IP3), NF, Psat, and Voltage/`Vd` (→VDD). Model + product URL
  come from `a.pst-part-ref-name` (`/products/p/{MODEL}`).
- **QRV-A-4** — Cell quirks: `"N/A"` / empty `""` = not specified; `Frequency Min
  = "DC"` means DC-coupled → `0.0`; VDD is a `"X to Y"` range (or a single value);
  GaN parts label supply `Vd` (map to VDD) and `Vg` (gate, ignore); some numeric
  cells carry commas (`"1,000"`) or trailing qualifiers.

## Open Questions

> These are **decided for v1** but deliberately left open so they can be changed
> later without hunting through the code.

- **QRV-OQ-1 — Spatium `Gain` = `Small Signal Gain`** *(confirmed 2026-07-01,
  revisitable).* Spatium is a high-power SSPA that lists **two** gain columns:
  `Small Signal Gain` (linear-region gain) and `Power Gain` (compressed gain near
  saturation, ~6–13 dB lower on the same part — e.g. QPB0206N: 30–33 dB vs
  18–19 dB). The adapter maps **`Small Signal Gain` → `Gain`** so it is
  apples-to-apples with the plain `Gain` reported by the other 11 categories (all
  small-signal). **Revisit if power-gain ever becomes the more relevant figure.**
- **QRV-OQ-2 — Include CATV** *(confirmed 2026-07-01, revisitable).* All **12**
  categories are kept, including `CATV Amplifiers` and `CATV Hybrid Amplifiers`
  (cable-TV broadband amplifiers, 5–1800 MHz). They are genuine amplifiers but a
  specialised sub-domain: freq in **MHz**, output in **dBmV**, plus CSO/CTB
  distortion specs — so they only map to `freq_range` (MHz), `Gain`, `NF`, `VDD`
  (their `Pout [dBmV]` maps to no canonical param). **Revisit — drop the 2 CATV
  categories (~85 parts) if the finder should be RF/microwave-only.**
- **QRV-OQ-3** — **Size, MSL, and Temperature are not usable from the listing
  page** and are left UNKNOWN in v1 (Option A, consistent with the other
  adapters). `Package [mm]` is a package-outline string present only for packaged
  parts (`"N/A"` for bare **Die**; the die's real size is datasheet-only as
  `Die Dimensions`). MSL and Temperature are datasheet-PDF only. Their enrichment
  would be a future datasheet fallback, not this adapter — see
  [t8-plan.md](t8-plan.md) §6.

## Definition of Done

- The system returns real amplifier candidates from Qorvo (category-filtered to
  the 12 amplifier types), each with its on-page RF params (freq, Gain, P1dB,
  IP3, NF, Psat, VDD as available), in a single robots-compliant request.
