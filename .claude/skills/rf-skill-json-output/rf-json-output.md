# RF Search — Structured Output Contract (Agent SDK)

The canonical, fixed schema for the machine-readable result. **Load this at Step 4 (reporting).** The skill is driven by `rf_finder`'s Agent SDK wrapper (`rf_finder/agent/skill_runner.py`): `run_agent_skill(...)` runs this skill with an `output_format` JSON schema, and the skill's **final result** is exposed to the caller as `ResultMessage.structured_output`. So the deliverable is a **returned structured value, not a file** — nothing is written to disk. The GUI's "AI Search" button maps the returned components straight into its results table (`_deliver_skill_results`); this path does **not** re-verify through `rf_finder`'s Python `verifier` — the skill's own verdict is what the user sees.

Content rules — *which* part is returned at all, the verdict vocabulary, the 80% partial-verification gate, the exhaustiveness of the coverage record — are **not** repeated here; they live in `SKILL.md` (Core definitions → Verdicts, the 80% rule, Outcome categories, and Step 4). This file fixes only the **output shape**.

The structured result is the machine deliverable; the Hebrew report (matches table, rejected list, coverage journal) is still produced **as streamed progress text** in the same run — the GUI discards that progress (`on_text` is a no-op) and shows only the returned components, while a chat/Claude-Code run shows the full report. The structured result never replaces the proof-of-work; they travel side by side.

---

## Result shape

A single JSON **object** with one key, `components`, an array of returned components (✅ full matches and every ⚠️ borderline that clears the 80% partial-verification gate — see SKILL.md). A run with no matches returns `{ "components": [] }` (an empty list is a valid, meaningful result — the streamed coverage statement explains it). This mirrors the SDK's `COMPONENT_SCHEMA` in `skill_runner.py`.

```json
{
  "components": [
    {
      "model": "AMM-6702",
      "manufacturer": "Example RF",
      "url": "https://example.com/datasheets/AMM-6702.pdf",
      "verdict": "match",
      "source": "datasheet",
      "params": {
        "freq_range":  { "value": [2.0, 6.0],    "unit": "GHz" },
        "Gain":        { "value": 18.0,           "unit": "dB" },
        "P1dB":        { "value": 22.0,           "unit": "dBm" },
        "Psat":        { "value": 24.0,           "unit": "dBm" },
        "NF":          { "value": 2.5,            "unit": "dB" },
        "IP3":         { "value": 35.0,           "unit": "dBm" },
        "VDD":         { "value": [3.0, 5.0],     "unit": "V" },
        "Size":        { "value": 4.0,            "unit": "mm" },
        "MSL":         { "value": 3,              "unit": "" },
        "Temperature": { "value": [-40.0, 85.0],  "unit": "degC" }
      }
    }
  ]
}
```

## Component fields

| Field | Required? | Content |
|---|---|---|
| `model` | **yes** | Part number (English, verbatim from the vendor). |
| `manufacturer` | **yes** | Manufacturer name — the **real maker** of the part, not the aggregator/source it was found on. |
| `url` | **yes** | The closest link to the part itself — prefer the part's **own datasheet PDF**; for an access-blocked ⚠️ match (datasheet unreachable) use the aggregator/product page instead. |
| `verdict` | shown by GUI | Short label the results table displays as-is: `"match"` for a ✅ full match; `"partial N/R"` for a ⚠️ partial-verified match (the 80% rule — N of R required params verified, e.g. `"partial 4/5"`); `"not-verified"` for a ⚠️ access-blocked `not datasheet-verified` match. |
| `source` | recommended | Provenance of the values in `params`: `"datasheet"` (read from the manufacturer datasheet) or `"table"` (a parametric-site/catalog table — the access-blocked ⚠️ case). |
| `params` | recommended | Object keyed by **canonical parameter name** → `{value, unit}`. See the full parameter table below. |

**Schema note (dependency for the user's SDK step).** The SDK's `COMPONENT_SCHEMA` in `skill_runner.py` currently declares only `model`, `manufacturer`, `url`, `verdict` (with `model`/`manufacturer`/`url` required). The skill returning `source` and `params` is harmless, but those two fields only reach the caller once that schema is **widened** to include them — that is the next SDK-side task. The GUI today reads only `model`, `manufacturer`, `url`, `verdict`.

## `params` — the FULL supported set

The keys are the system's canonical parameter names, **case-sensitive**, and they are the complete set the amplifier module and `rf_finder`'s `PARAMETERS` define — **every** parameter below is a valid key; the skill emits whichever ones it actually found for a given part. A non-canonical key is ignored downstream — never invent or alias a name.

| Canonical key | `value` shape | Example `value` | `unit` (raw, as found) |
|---|---|---|---|
| `freq_range` | `[low, high]` continuous range | `[2.0, 6.0]` | `"GHz"` / `"MHz"` |
| `Gain` | scalar number | `18.0` | `"dB"` |
| `P1dB` | scalar number | `22.0` | `"dBm"` / `"W"` / `"mW"` |
| `Psat` | scalar number | `24.0` | `"dBm"` / `"W"` / `"mW"` |
| `NF` | scalar number | `2.5` | `"dB"` |
| `IP3` | scalar number | `35.0` | `"dBm"` |
| `VDD` | array of discrete supply options | `[3.0, 5.0]` | `"V"` |
| `Size` | scalar number | `4.0` | `"mm"` |
| `MSL` | scalar number (integer 1–5) | `3` | `""` (no unit) |
| `Temperature` | `[low, high]` continuous range | `[-40.0, 85.0]` | `"degC"` |

## `params` rules

- **`value` shape by kind** (see the table): scalar parameters → a single number; `freq_range` and `Temperature` → a two-element `[low, high]` array; `VDD` → an array of the **discrete** supply options the part supports (not a continuous range — list only the values actually offered).
- **`unit` is the string as found on the source — no normalization.** Give the raw unit exactly as the datasheet/table states it. Any downstream unit conversion is the Python side's job; converting here would hide a reading error.
- **Omit any parameter that was not found** — do not emit a `null`, a `0`, or an empty object for it. A key present means a real value was found on the stated `source`.
- **At least one primary RF parameter** (`freq_range`, `Gain`, `P1dB`, `Psat`, `NF`, `IP3`) must be present — a component carrying only secondary params (`VDD`/`Size`/`MSL`/`Temperature`) gives no RF spec to check and must not be returned.
