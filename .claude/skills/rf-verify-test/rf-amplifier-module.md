---
name: rf-amplifier-module
description: Amplifier-specific parameter module for the RF Component Parametric Search engine. Load this module whenever the requested component is an amplifier (LNA, driver, gain block, power amplifier, medium-power amplifier, etc.) and the user gives amplifier electrical parameters — frequency range, Gain, P1dB, OIP3, NF, Psat, VDD, Size, MSL, operating temperature. It defines the ONLY parameters that may be used as amplifier search filters, their units, comparison directions, derived-value formulas, and physics sanity checks. Use together with the general RF Component Parametric Search engine, which owns the workflow, verification discipline, report format, and vendor lists. This module supplies the parameter layer only.
---

# Amplifier Parameter Module

This module plugs into the general **RF Component Parametric Search** engine. The engine owns the workflow (parse → clarify → search → verify → re-verify → report), the parameter-handling rules (suitability, comparison semantics, column preference, conversions), and the vendor lists. This module supplies the **amplifier-specific parameter layer**: the searchable parameters, their canonical units, directions, derivation formulas, fixed conventions, and sanity checks.

Read the general rules in the engine's "How parameters work" section first — the definitions of `min` / `max` / `contains`, the "parameter must be stated on the datasheet or be derivable, else unsuitable" rule, the guaranteed-column-over-typ preference, and the shown-conversion requirement all apply here unchanged. This module only fills in the concrete parameters those rules operate on.

## Scope

This module covers **amplifiers only**. If the requested component is a mixer, filter, attenuator, switch, coupler, or anything else, this module does not apply — tell the user there is no parameter module for that component type yet and ask how to proceed rather than reusing amplifier parameters.

## Parameter Dictionary

**Hard rule: only the parameters in this table may be used as amplifier search filters.** If the user's spec contains an electrical term not listed here, raise it in the engine's Step 1 clarification round — never improvise a filter from an unlisted parameter. Parameters the user did NOT specify are ignored entirely.

| Param | Meaning | Canonical unit | Accepted units | Comparison | Notes |
|---|---|---|---|---|---|
| `freq_range` | Frequency range | GHz | GHz, MHz | contains | Requested band ⊆ datasheet **specified** band (not just "operating"). |
| `P1dB` | **Output** 1 dB compression (OP1dB) | dBm | dBm, W, mW | min | Output-referred by fixed convention. If only IP1dB is given: OP1dB = IP1dB + Gain − 1 dB (derived → ⚠️). |
| `Gain` | Small-signal gain | dB | dB | min | Floor only. No hard upper bound in current policy. |
| `NF` | Noise figure | dB | dB | max | Must hold across the full requested band, not one point. |
| `IP3` | **OIP3** (output IP3) | dBm | dBm | min | Output-referred by fixed convention. If only IIP3 is given: OIP3 = IIP3 + Gain (derived → ⚠️). |
| `Psat` | Saturated output power | dBm | dBm, W, mW | min | Derive only from an explicit datasheet relation; otherwise absent = unsuitable. |
| `VDD` | Supply voltage | V | V | contains | **Treatment not finalized** — if the user specifies VDD, ask how to treat it in Step 1 before searching on it. |
| `Size` | Package / module size | mm | mm | max | Default: each specified dimension compared independently (L ≤ L, W ≤ W, H ≤ H), package body dimensions. **This default is not finalized** — confirm with the user if size is a hard constraint. |
| `MSL` | Moisture sensitivity level | — (none) | — | max | A **single integer value in the range 1–5** (not a range). Enforced only if the user specifies it. If specified and the datasheet has no MSL rating (e.g. connectorized modules, bare die) → unsuitable. |
| `Temperature` | Operating temperature range | °C | °C | contains | Part's rated range ⊇ requested range. |

## Site-screen classification (Step 2.7)

Each parameter is classified for the engine's two-stage filter (see the general rules' "Where each parameter is checked" section): **site-checkable** parameters are screened cheaply on parametric sites/catalog tables before any datasheet is opened; **datasheet-only** parameters are deferred to Step 3. Site-checkable parameters carry a **guard band `G`** — at Stage 1 a part is rejected on such a parameter only when the site value misses by more than `G`; within `G`, absent from the site, or absent from the query, it promotes. Guard bands are ≥ the typical typ-vs-guaranteed gap, so the screen never drops a part a guaranteed-column read would have passed. Every site-checkable parameter is still re-confirmed against the datasheet in Step 3.

| Param | Where checked | Guard band `G` |
|---|---|---|
| `freq_range` | site-checkable | 0 — catalog fact; reject only if the site's listed band cannot contain the request (specified-vs-operating nuance resolved at the datasheet). |
| `Gain` | site-checkable | 3 dB — covers typ-vs-guaranteed-min spread. |
| `P1dB` (OP1dB) | site-checkable | 3 dB — covers typ-vs-min spread, unit/condition variation. |
| `IP3` (OIP3) | site-checkable | 3 dB — covers typ-vs-min spread, frequency-point variation. |
| `NF` | site-checkable | 1 dB — condition-sensitive; keep tight but non-zero. |
| `Psat` | datasheet-only | — inconsistently listed on sites; confirm at datasheet. |
| `VDD` | datasheet-only | — treatment unfinalized (see Open questions); do not screen. |
| `Size` | datasheet-only | — package body dimensions live on the datasheet. |
| `MSL` | datasheet-only | — rarely on parametric sites. |
| `Temperature` | datasheet-only | — rated range lives on the datasheet. |

Site tables routinely mix typ/guaranteed values and single-frequency points — that unreliability is exactly why a site-checkable miss must exceed the guard band to reject, and why every survivor is still fully verified in Step 3.

## Fixed conventions (do not ask about these)

These resolve, in advance, ambiguities the engine's Step 1 would otherwise raise:

- **P1dB is output-referred (OP1dB).** Do not ask input vs output.
- **IP3 is output-referred (OIP3).** Do not ask input vs output.
- **Gain is a floor (`min`).** No hard upper bound in current policy; only confirm an upper bound if the user explicitly gives a two-sided gain range.
- **Guaranteed min/max columns are preferred; typ only as a ⚠️ fallback.** Do not ask about the min/typ/max policy.

## Open questions (ask in Step 1 if the user specifies them)

- **VDD** — comparison treatment is not finalized. If the user gives a VDD value, ask how it should be matched before filtering on it.
- **Size** — the per-dimension default above is provisional. If size is a hard constraint, confirm whether the user means per-dimension, longest-dimension, or footprint.

## Derived-value formulas

When a required parameter is not stated directly on the datasheet but the inputs are, compute it, **show the calculation explicitly**, and mark the result ⚠️ (typ-grade) unless every input is itself a guaranteed min/max value:

- `OP1dB = IP1dB + Gain − 1 dB` — use when only input P1dB is given.
- `OIP3 = IIP3 + Gain` — use when only input IP3 is given.
- Unit conversions on power parameters (`P1dB`, `Psat`) between dBm / W / mW, e.g. `2 W → +33.0 dBm`.

If neither a stated value nor a valid derivation is available for a parameter the user specified, the part is **unsuitable** — "parameter not stated in datasheet" (per the engine's core suitability rule).

## Sanity checks (amplifier physics)

Apply these during the engine's Step 3 verification and Step 3.5 re-verification. A violation is a red flag: re-read the source before trusting the value.

- **OIP3 vs OP1dB**: OIP3 is normally ~8–13 dB above OP1dB for the same part. A datasheet where OIP3 < OP1dB was probably misread.
- **NF floor**: NF below ~1 dB for a non-cryogenic part above 6 GHz deserves a second look.
- **Gain per stage**: gain above ~15 dB per stage deserves a second look (implausibly high for a single stage).

These are amplifier-specific; other component modules will define their own.
