# RF Search — JSON Output Contract

The canonical, fixed schema for the machine-readable result file. **Load this at Step 4 (reporting).** Every run writes one JSON file whose shape is identical run to run, so the downstream Python form (`rf_finder`) can consume it without guessing. This file mirrors the `rf_finder` `Candidate` model exactly: `model`, `manufacturer`, `url`, `raw_params{canonical_name -> RawValue{value, unit}}`, `source`.

Content rules — *which* part is returned at all, the verdict vocabulary, the 80% partial-verification gate, the exhaustiveness of the coverage record — are **not** repeated here; they live in `SKILL.md` (Core definitions → Verdicts, the 80% rule, Outcome categories, and Step 4). This file fixes only the **output shape**.

The JSON file is the machine deliverable that feeds the Python form; the Hebrew chat report (matches table, rejected list, coverage statement) is produced **in addition**, exactly as before — the JSON never replaces the proof-of-work the user reads in chat.

---

## File shape

A single JSON **array** at the top level. Each element is one returned component (✅ full matches and every ⚠️ borderline that clears the 80% partial-verification gate — see SKILL.md). A run with no matches writes `[]` (an empty array is a valid, meaningful result — the chat coverage statement explains it).

Write it UTF-8, `ensure_ascii=false`, pretty-printed (2-space indent).

## Object fields (exactly these five, in this order)

| Field | Content |
|---|---|
| `model` | Part number (English, verbatim from the vendor). |
| `manufacturer` | Manufacturer name — the **real maker** of the part, not the aggregator/source it was found on. |
| `url` | The closest link to the part itself — prefer the part's **own datasheet PDF**; for an access-blocked ⚠️ match (datasheet unreachable) use the aggregator/product page instead. |
| `source` | Provenance of the values in `params`: `"datasheet"` when read from the manufacturer datasheet, `"table"` when they rest on a parametric-site/catalog table (the access-blocked ⚠️ case). One of these two strings only. |
| `params` | Object keyed by **canonical parameter name** → a `{value, unit}` object. See the full parameter table below. |

## `params` — the FULL supported set

The keys are the system's canonical parameter names, **case-sensitive**, and they are the complete set the amplifier module and `rf_finder`'s `PARAMETERS` define — **every** parameter below is a valid key; the skill emits whichever ones it actually found for a given part. A non-canonical key is ignored by the Python form — never invent or alias a name.

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

### Full example — every supported parameter present

A part need not carry all of these; this example shows the shape of **each** key so nothing is ambiguous. Omit any parameter that was not actually found.

```json
[
  {
    "model": "AMM-6702",
    "manufacturer": "Example RF",
    "url": "https://example.com/datasheets/AMM-6702.pdf",
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
```

## `params` rules

- **`value` shape by kind** (see the table): scalar parameters → a single number; `freq_range` and `Temperature` → a two-element `[low, high]` array; `VDD` → an array of the **discrete** supply options the part supports (not a continuous range — list only the values actually offered).
- **`unit` is the string as found on the source — no normalization.** Give the raw unit exactly as the datasheet/table states it. The Python form converts to canonical units itself; converting here would hide a reading error.
- **Omit any parameter that was not found** — do not emit a `null`, a `0`, or an empty object for it. A key present means a real value was found on the stated `source`.
- **At least one primary RF parameter** (`freq_range`, `Gain`, `P1dB`, `Psat`, `NF`, `IP3`) must be present — a component carrying only secondary params (`VDD`/`Size`/`MSL`/`Temperature`) gives the form no RF spec to check and must not be emitted.

## Where the file is written

Write the array to a single file and tell the user its path in the chat report. Default path: the current working directory as `rf-results.json`, unless the user named another location. State the absolute path in the coverage statement so the Python form (and the adapter that reads it) can point at it.
