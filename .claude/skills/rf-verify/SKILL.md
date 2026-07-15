---
name: rf-verify
description: Verify ONE already-discovered RF/microwave component against a multi-parameter spec, using 100%-reliable datasheet reading via Gemini. Given a single candidate (model, manufacturer, url) plus the requested parameters, it fetches and reads the datasheet, compares every required parameter, applies the 80% partial-verification rule, and returns that one part's verdict — match / partial / not-verified / rejected. Used by the pipelined AI Search conductor, which fires one rf-verify run per candidate that rf-discovery surfaces, so each component is verified independently the moment it is found. Not a search skill — it never discovers parts; pair it with rf-discovery.
---

# RF Component Verification (single candidate)

Verify **one** already-discovered candidate against the spec, and **prove** the verdict. You are handed a single part (model, manufacturer, url) plus the requested parameters; your only job is to decide, reliably, whether *this one part* matches — and to say exactly why. A false "match" that fails on one parameter erodes trust; an honest "rejected — NF is 4 dB, needs ≤ 3" is a perfectly good answer, but an unverified guess never is. You do **not** search for other parts — discovery is `rf-discovery`'s job; a conductor runs you once per candidate.

## Input

The caller gives you: the **candidate** (`model`, `manufacturer`, `url`) and the **spec** (the requested parameters, each with value + direction). Verify that candidate against that spec. Nothing else is in scope — do not go looking for sibling parts, alternatives, or other vendors.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain, OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Required reference files

Before verifying, load both:

- **`rf-parameter-rules.md`** — the general, component-agnostic rules for how any parameter is handled (the datasheet-suitability rule, `min`/`max`/`contains` semantics, guaranteed-column-over-typ, mandatory shown conversions).
- **The per-component module matching the candidate's component type** (e.g. `rf-amplifier-module.md` for amplifiers) — the parameters, their units, directions, derivation formulas, fixed conventions, and physics sanity checks.

Only parameters defined in the loaded component module are checked. If no module exists for the component type, say so and stop rather than improvising.

## Core definitions

### Verdicts

- **✅ full match** — every required parameter confirmed from the manufacturer datasheet/catalog table.
- **⚠️ borderline** — meets spec but only as typ, or exactly at the limit, or partially verified (the 80% rule below), or the access-blocked case below.
- **❌ rejected** — a required parameter fails; state which and by how much.

### Partial-verification acceptance — the 80% rule

A part need **not** have every required parameter confirmed to be returned as a good result — but the tolerance is bounded and precise. This rule decides whether a part that fell short of full datasheet verification is still returned or is excluded. Over the parameters the spec actually specified (call the count **R**), classify each required parameter after verification:

- **verified-and-matching** — confirmed to meet the spec from a primary source: read from the manufacturer datasheet and passing, **or** a site-checkable parameter already cleared beyond its guard band by the discovery screen and passed to you as confirmed (it counts as confirmed).
- **failed** — a datasheet value that misses the spec.
- **unverified** — neither: not stated on the datasheet, TBD, a datasheet-only parameter that could not be read, or a parameter left unconfirmed because the datasheet was inaccessible.

Decision (apply in order):

1. **Any failed parameter → ❌ rejected.** The 80% rule never rescues a real miss; a datasheet value that loses against the spec rejects the part as before.
2. **All R verified-and-matching, none unverified → ✅ full match** (per Verdicts).
3. **0 failed and (verified-and-matching ÷ R) ≥ 0.80 (but not all) → ⚠️ partial-verified** — returned as a good result, flagged **"אומת חלקית — N/R פרמטרים אומתו"**, naming the unverified parameters.
4. **0 failed and (verified-and-matching ÷ R) < 0.80 → excluded** — not a good result. Reported as `insufficient verification`, listing which required parameters are unverified. **Not** a parameter failure — never conflated with a ❌.

The ratio is computed over required (spec) parameters only; parameters not in the spec are never counted in **R**. This rule makes precise the otherwise-vague "one spec unverifiable" case: the exact gate is 80% verified-and-matching with zero failures.

### site-checkable vs datasheet-only

The loaded component module classifies each parameter as **site-checkable** (reliably shown/filterable on parametric sites and catalog tables) or **datasheet-only** (reliably found only on the datasheet). A site-checkable parameter the caller already cleared beyond its guard band during discovery counts as verified-and-matching and need not be re-extracted; everything else is confirmed here against the datasheet.

### The site-data rule (site data cannot confirm)

Site data (search snippets, distributor/parametric tables) may have *promoted* this candidate in, but **cannot confirm a match** (typ-at-one-frequency, missing conditions, plain errors). A part is confirmed or rejected here only against an **actual datasheet value** (what Gemini extracted). **Never silently skip** — an inaccessible datasheet is logged and handled, not ignored.

### Outcome categories (used in the verdict/reason)

- **`not datasheet-verified`** — passed **every** specified site-checkable parameter at 100% (clear of the guard band) yet the datasheet was not checked (the access-blocked ⚠️ case below). The **only** access-blocked outcome that carries this flag.
- **`insufficient verification`** — reached datasheet-check with zero outright failures, but fewer than 80% of the required parameters ended verified-and-matching (the 80% rule). Excluded from the results, logged with the unverified parameters. **Not** a parameter failure, and **not** the same as `not datasheet-verified`.
- **`datasheet inaccessible`** — the datasheet could not be fetched; log the alternative sources tried and whether the part ended as a ⚠️ not-verified match or an unverifiable reject.

### Access-blocked datasheet logic

A blocked datasheet is an *access* failure, never a parameter failure. First **exhaust alternative datasheet sources, logging each one tried**: everything.rf's linked/mirrored datasheet, a search-engine cached copy, a distributor-hosted PDF, and the `resources.ampheo.com/static/datasheets/<vendor>/<part>.pdf` mirror pattern. Only if **all** fail, classify by the module:

- **Every** specified parameter is site-checkable, was actually shown on a site, and clears the spec **beyond** its guard band (merely inside the guard band ≠ clear) → **⚠️ match, `not datasheet-verified`** (`source: "table"`, an aggregator link as `url`, flag "לא אומת — גישה ל-datasheet חסומה"). **Never** shown as ✅.
- **Otherwise** (some specified parameter is datasheet-only, or is site-checkable but was never shown on a site, or passed only *within* its guard band) → apply the **80% rule** over the required parameters, counting the site-checkable ones clear beyond their guard band as verified-and-matching: if ≥80% are verified-and-matching with zero failures → ⚠️ partial-verified (returned, flagged); if <80% → **`insufficient verification`**, an unverifiable reject labelled distinctly "לא נפסל על פרמטר — נדרש אימות ב-datasheet שלא היה נגיש; כדאי לשקול פנייה ליצרן" — never conflated with a real parameter failure.

## Workflow

### Step 1 — Verify the candidate against primary sources

A candidate becomes a match only after every required parameter is confirmed against the **manufacturer's datasheet** — or, short of that, after it clears the **80% rule** (Core definitions), which decides whether a partially-verified part is still returned or is an `insufficient verification` reject. **Reading the datasheet is ALWAYS delegated to Gemini — the skill never opens, downloads-to-read, or decodes the PDF in its own context.** Hand the datasheet to the runner (see *Reading datasheets — always via Gemini* below); it returns the extracted values as JSON, and you judge the match from them. Distributor summaries and snippets routinely show typ at one frequency point, omit conditions, or are wrong — per the site-data rule: a part is rejected here only against an actual datasheet value (what Gemini extracted from the datasheet); site data may only have promoted it in.

**Efficiency:** extract only the parameters still open. A site-checkable parameter the caller marked as already cleared **beyond its guard band** during discovery need not be re-extracted — pass the runner only the datasheet-only and borderline parameter names. (Such a guard-band-clear site parameter counts as **verified-and-matching** for the 80% rule.)

For each parameter record: the actual value, whether it is min/typ/max, and any conditions (temperature, frequency point vs full band). Watch for:

- Specs guaranteed only at +25°C vs over temperature — note which.
- NF/gain at a single frequency vs across the band. The requested band must be inside the datasheet's *specified* range, not just the "operating" range.
- Column-header typos (a "Min/Typ" header on a Noise Figure column almost certainly means Max/Typ — flag, don't assume).
- Parameters listed TBD or absent → **unverified** for the 80% rule (never a match); if the whole part then falls below 80%, it is `insufficient verification`. Say "requires manufacturer contact", never guess.

Record the **margin** per parameter (e.g. OIP3 required ≥30, actual +37 → margin +7dB). Assign a verdict (see Verdicts), applying the 80% rule when not every required parameter was datasheet-confirmed.

**If the datasheet cannot be fetched** (bot-block / 409 / 404 / not indexed): follow the Access-blocked datasheet logic in Core definitions.

### Step 2 — Independent re-verification (not run in the current Gemini-reads mode)

Reading errors are real, and normally this step re-reads the datasheet from scratch to catch them. That mechanism relied on two things this configuration removes — the agent **re-reading the PDF**, and re-checking each value's **quoted string + location**. Both are disabled here (datasheet reading is always Gemini's, and no quote/location is captured), so **independent re-verification is not performed**: a reported match rests on Gemini's single extraction. Note this plainly in the verdict/reason.

**Still do the cheap checks that need no re-read:**

- Apply the loaded module's **physics sanity checks** to Gemini's extracted values (e.g. OIP3 is normally above OP1dB; the NF floor; gain-per-stage). A violation is a red flag → re-extract that parameter via the runner before trusting it.
- A ⚠️ **access-blocked** match (datasheet unreachable, site values clear of the guard band) is re-checked against the *site* values only — confirm each still clears the spec beyond its guard band — and stays ⚠️ `not datasheet-verified`.

**To restore a real trust layer later** without breaking the rules, re-enable this step as a **second, independent Gemini extraction**: call the runner again on the same datasheet and diff the two JSON results; any discrepancy → re-extract and resolve, or downgrade to ⚠️.

### Reading datasheets — ALWAYS via Gemini (mandatory, never the skill itself)

**This is mandatory and has no fallback.** Whenever you need to read or decode data from a datasheet PDF, hand the whole job to Gemini — **never** open, download-to-read, or decode the PDF in your own context. A datasheet URL points at a **PDF file** (binary), not readable text, so its bytes must be fetched and decoded; that entire job is Gemini's, via the runner. The tools live in `tools/`:

- `config.py` — resolves the provider/model from `rf-llm.env` (Gemini by default; the single place to switch models).
- `pdf.py` + `extractor.py` — decode the PDF **in memory** and send its text to Gemini, which returns values-only JSON.
- `run_extract.py` — the single entry point that ties them together (fetch → decode in memory → Gemini → JSON). Nothing is written to disk.

**Invocation:**

```
python "${CLAUDE_SKILL_DIR}/tools/run_extract.py" --url "<datasheet URL>" --params "Gain,P1dB,NF,OIP3"
```

`--file <path>` reads a local PDF instead of a URL; `--requirements-file <reqs.json>` passes the parameter names from a file instead of `--params`. It prints **one JSON object**:

```
{ success, provider, model, parameters, error, sources }
```

`parameters` maps each requested name to `{unit, min, typ, max, value, condition}` or `null` (not stated on the datasheet). Exit code 0 = success, 1 = failure. A `success:false` is a fetch/read failure → apply the **Access-blocked datasheet logic** (Core definitions); never a silent match or reject.

**First action:** confirm the config — `RF_LLM_PROVIDER`, `RF_LLM_MODEL`, and the provider key are set in `tools/rf-llm.env`, and the provider is registered in `extractor._get_runtime` (currently `mock` / `local` / `openai` / `gemini`). If the config is missing or broken, **say so and stop** — there is no "read the PDF yourself" fallback.

**Gemini extracts; the skill judges.** The model returns values only — no verdict. Map the JSON onto `rf-parameter-rules.md` + the component module, compute margins, and assign ✅/⚠️/❌ (applying the 80% rule for a part not fully datasheet-confirmed):

- `min` / `typ` / `max` → for a `min` or `max` parameter, compare against the **guaranteed column** the direction needs (the `min` field for a `min` parameter, the `max` field for a `max` one); use `typ` **only** when the guaranteed column is `null`, then mark the verdict ⚠️ "typ only". For a `contains` parameter (frequency band, temperature range), the range comes back as `min`..`max` — check that range **fully contains** the requested one.
- `null` (parameter not stated) → the datasheet-suitability rule applies: this parameter is **unverified** for the 80% rule (reject the *part* only if it then falls below 80% — never guess a value the model returned as `null`).
- `value` → **only** categorical/discrete parameters (MSL, package type, size string) and explicitly-enumerated discrete supply lists — numeric ranges live in `min`/`max`, not here.
- `condition` → the operating point; for a band-dependent parameter, confirm the returned value covers the **requested band**. The extractor returns one object per parameter, so a multi-band part may need a focused re-extraction at the requested band.
- Compute and **show** each margin and unit conversion (`2 W → +33.0 dBm; required ≥ +30 dBm; margin +3.0 dB`).

State that datasheet reading was done via Gemini, and which provider/model.

## Output — one component result

Return a single JSON object `{ "components": [ ... ] }`:

- If the candidate **qualifies** (✅ full match, ⚠️ partial-verified that clears the 80% rule, or ⚠️ access-blocked `not datasheet-verified`) → the list has **exactly one** entry: `{ "model", "manufacturer", "url", "verdict" }` (the same four fields `COMPONENT_SCHEMA` defines). `verdict` is `"match"` (✅), `"partial N/R"` (⚠️ partial-verified), or `"not-verified"` (⚠️ access-blocked).
- If the candidate **does not qualify** (❌ rejected, or `insufficient verification`) → the list is **empty** `[]`.

In your text (chat) output, **always state the verdict and the reason** — for a match: the per-parameter margins; for a reject: the failing parameter and its actual value, or the unverified parameters for an `insufficient verification` / access-blocked-unverifiable case. The conductor logs this text into the run's rejected list / coverage record, so it must be present even when the component list is empty.
