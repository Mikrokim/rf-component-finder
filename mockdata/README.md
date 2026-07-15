# Mock component dataset (RF_SKILL_MODE=test)

Local, offline dataset the **test** skills (`rf-discovery-test`, `rf-verify-test`)
read instead of the web + Gemini. Loaded only when `RF_SKILL_MODE=test`; the real
skills never touch this folder.

Three files, one per discovery path — this mirrors the real skill's three
independent discovery paths, so the same part appearing in two files exercises
the conductor's on-the-fly dedup:

- `path_a.json` — Path A (parametric aggregators: everything.rf / Mouser / Digi-Key / Octopart)
- `path_b.json` — Path B (part-graph traversal: siblings / alternatives)
- `path_c.json` — Path C (vendor-cache catalog sweep)

## Entry schema

```json
{
  "components": [
    {
      "model": "ASL4020",
      "manufacturer": "Aelius",
      "url": "https://example.com/asl4020",
      "params": {
        "freq_range": "14-15 GHz",
        "Gain": "22 dB",
        "P1dB": "25 dBm",
        "IP3": "37 dBm",
        "NF": "2.0 dB"
      }
    }
  ]
}
```

- **`params` keys are the canonical amplifier names** from
  `.claude/skills/rf-verify/rf-amplifier-module.md`: `freq_range`, `Gain`, `P1dB`,
  `NF`, `IP3`, `Psat`, `VDD`, `Size`, `MSL`, `Temperature`. Values carry their
  unit as a string, exactly as a datasheet/site would show them.
- **Include *all* parameters a query might check** (not only the site-checkable
  ones), because in test mode `rf-verify-test` reads its values from here instead
  of a datasheet.
- **Omit a parameter** to simulate "not stated on the datasheet" — verify then
  marks it unverified and the 80% rule decides the verdict.

## How the two test skills use this data

- `rf-discovery-test` runs its Step 2.7 screen against the **site-checkable**
  params here (`freq_range`, `Gain`, `P1dB`, `IP3`, `NF`) and emits every
  candidate that isn't a clear miss (it is deliberately permissive).
- `rf-verify-test` looks up the candidate by `model` across these three files and
  runs the **full** match (all params, guaranteed-column/`min`/`max`/`contains`
  semantics, margins, the 80% rule) against the user's query.

## Design guidance for the real ~20 components

To exercise every branch of the pipeline, include:
- a few parts in **two** path files (same `model` + `manufacturer`) → dedup;
- a part whose band **cannot contain** the usual query → screened out at Step 2.7;
- a part that **omits** a queried param → verify's ⚠️ partial / 80%-rule path;
- a spread of clean ✅ matches and ❌ rejects → the form renders each verdict.

> The dataset holds **20 real amplifiers** pulled from vendor datasheets
> (Ciao Wireless, Aelius, PMI, Mercury, Altum, Narda-MITEQ, Erzia, Cernex, BeRex).
> Values are the guaranteed min (Gain/P1dB) / max (NF) columns where the datasheet
> gives them, else the stated typ. Against a 14-15 GHz query the set exercises all
> branches: 16 survive the screen, 5 are screened out (out-of-band), 6 omit NF
> (verify partial path), and ASL4020 is duplicated across paths (dedup).
