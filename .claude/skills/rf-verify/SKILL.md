---
name: rf-verify
description: Verify ONE already-discovered RF/microwave component against a multi-parameter spec, using 100%-reliable datasheet reading via Gemini. Given a single candidate (model, manufacturer, url), the requested parameters, and rf-discovery's per-parameter site-screen results, it settles only what the sites could not — reading the datasheet via Gemini for those parameters, and not opening it at all when the sites already answered the whole spec — then applies the 80% partial-verification rule and returns that one part's verdict: match / partial / rejected. Used by the pipelined AI Search conductor, which fires one rf-verify run per candidate that rf-discovery surfaces, so each component is verified independently the moment it is found. Not a search skill — it never discovers parts; pair it with rf-discovery.
---

# RF Component Verification (single candidate)

Verify **one** already-discovered candidate against the spec, and **prove** the verdict. You are handed a single part (model, manufacturer, url) plus the requested parameters; your only job is to decide, reliably, whether *this one part* matches — and to say exactly why. A false "match" that fails on one parameter erodes trust; an honest "rejected — NF is 4 dB, needs ≤ 3" is a perfectly good answer, but an unverified guess never is. You do **not** search for other parts — discovery is `rf-discovery`'s job; a conductor runs you once per candidate.

## Input

The caller gives you:

- the **candidate** — `model`, `manufacturer`, `url`;
- the **spec** — the requested parameters, each with value + direction;
- the **site-screen results** — one line per query parameter, recorded by `rf-discovery` at its Step 2.7 screen. Each carries a `status`, and that status is the site-level judgment **already made**; you act on it rather than redoing it:

| `status` | Meaning | What you do |
|---|---|---|
| `pass` | the site value cleared the spec **beyond** the parameter's guard band | count it **verified-and-matching — never re-extract it** |
| `borderline` | satisfies the spec only **inside** the guard band | settle it against the datasheet |
| `not_stated` | datasheet-only, or no site exposed it | settle it against the datasheet |
| `fail` | clearly missed, beyond the guard band | ❌ reject — terminal (Step 0) |

Verify that candidate against that spec. Nothing else is in scope — do not go looking for sibling parts, alternatives, or other vendors.

**If the site-screen results are missing or empty**, treat every spec parameter as `not_stated` and settle all of them against the datasheet. That is the correct fallback — slower, still correct. **Never invent a `pass`**: a parameter is confirmed from site data only when discovery actually recorded it as such.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain, OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Required reference files

Before verifying, load both:

- **`rf-parameter-rules.md`** — the general, component-agnostic rules for how any parameter is handled (the datasheet-suitability rule, `min`/`max`/`contains` semantics, guaranteed-column-over-typ, mandatory shown conversions).
- **The per-component module matching the candidate's component type** (e.g. `rf-amplifier-module.md` for amplifiers) — the parameters, their units, directions, derivation formulas, fixed conventions, and physics sanity checks.

Only parameters defined in the loaded component module are checked. If no module exists for the component type, say so and stop rather than improvising.

## Core definitions

### Verdicts

- **✅ full match** — every required parameter confirmed: from the manufacturer datasheet, from a `pass` site value (cleared beyond its guard band), or any mix of the two. When *every* parameter is `pass`, no datasheet is opened at all (Step 0 case 2).
- **⚠️ borderline** — meets spec but only as typ, or exactly at the limit, or partially verified (the 80% rule below), or the access-blocked case below.
- **❌ rejected** — a required parameter fails; state which and by how much.

### Partial-verification acceptance — the 80% rule

A part need **not** have every required parameter confirmed to be returned as a good result — but the tolerance is bounded and precise. This rule decides whether a part that fell short of full datasheet verification is still returned or is excluded. Over the parameters the spec actually specified (call the count **R**), classify each required parameter after verification:

- **verified-and-matching** — confirmed to meet the spec from a primary source: read from the manufacturer datasheet and passing, **or** recorded `pass` by the discovery screen (the site value cleared the spec beyond its guard band — see Input).
- **failed** — a datasheet value that misses the spec.
- **unverified** — neither: not stated on the datasheet, TBD, a datasheet-only parameter that could not be read, or a parameter left unconfirmed because the datasheet was inaccessible.

Decision (apply in order):

1. **Any failed parameter → ❌ rejected.** The 80% rule never rescues a real miss; a datasheet value that loses against the spec rejects the part as before.
2. **All R verified-and-matching, none unverified → ✅ full match** (per Verdicts).
3. **0 failed and (verified-and-matching ÷ R) ≥ 0.80 (but not all) → ⚠️ partial-verified** — returned as a good result, flagged **"אומת חלקית — N/R פרמטרים אומתו"**, naming the unverified parameters.
4. **0 failed and (verified-and-matching ÷ R) < 0.80 → excluded** — not a good result. Reported as `insufficient verification`, listing which required parameters are unverified. **Not** a parameter failure — never conflated with a ❌.

The ratio is computed over required (spec) parameters only; parameters not in the spec are never counted in **R**. This rule makes precise the otherwise-vague "one spec unverifiable" case: the exact gate is 80% verified-and-matching with zero failures.

### site-checkable vs datasheet-only

The loaded component module classifies each parameter as **site-checkable** (reliably shown/filterable on parametric sites and catalog tables) or **datasheet-only** (reliably found only on the datasheet). That classification is what discovery screens on: a site-checkable parameter can come back `pass`, `borderline`, or `fail`, whereas a datasheet-only parameter is always `not_stated` and is always settled here.

### The site-data rule (what site data settles, and what it does not)

Site data is trustworthy exactly where the guard band says it is — and the `status` discovery recorded *is* that judgment, already made:

- **`pass` → settles the parameter.** The site value cleared the spec **beyond** the guard band, and the guard band is precisely the margin that absorbs the typ-vs-guaranteed spread and unstated conditions which make raw site values untrustworthy. A value clear of it is not a value those errors could flip. Count it verified-and-matching; do not re-extract it.
- **`borderline` / `not_stated` → settle nothing.** Only an actual datasheet value (what Gemini extracted) settles these.
- **`fail` → rejects the part.** A clear miss beyond the guard band is definitive, and the datasheet gets no appeal (Step 0).

So site data both confirms and rejects — but only beyond the guard band, and never inside it. **Never silently skip** — an inaccessible datasheet is logged and handled, not ignored.

### Outcome categories (used in the verdict/reason)

- **`not datasheet-verified`** — **retired; no longer reachable — do not emit.** It marked a part that passed every specified site-checkable parameter clear of the guard band but whose datasheet went unchecked. That case is now **✅ at Step 0 case 2**: when the sites settle the whole spec, the datasheet is not *unchecked*, it is *not needed*, and the part is a full match. The category is kept here (and as the `"not-verified"` verdict in the output schema) only so it is recoverable if that ✅ decision is ever revisited.
- **`insufficient verification`** — reached datasheet-check with zero outright failures, but fewer than 80% of the required parameters ended verified-and-matching (the 80% rule). Excluded from the results, logged with the unverified parameters. **Not** a parameter failure, and **not** the same as `not datasheet-verified`.
- **`datasheet inaccessible`** — the datasheet could not be fetched after every alternative was tried through the runner; log each source tried and whether the part ended as a ⚠️ partial-verified match (80% rule) or an unverifiable reject.

### Access-blocked datasheet logic

A blocked datasheet is an *access* failure, never a parameter failure. First **exhaust alternative datasheet sources, logging each one tried**: everything.rf's linked/mirrored datasheet, a search-engine cached copy, a distributor-hosted PDF, and the `resources.ampheo.com/static/datasheets/<vendor>/<part>.pdf` mirror pattern.

**Hand every alternative to the runner — never fetch a PDF yourself.** Finding a candidate URL may well mean reading an HTML page (a product page that links its datasheet); reading the **PDF** is always the runner's job, exactly as in the primary case (see *Reading datasheets — ALWAYS via Gemini*). Try the alternatives **one runner call per URL, in order, until one returns `success: true`** — never one call listing several `--url`s (that merges them and aborts on the first dead link; see the invocation notes).

Only if **all** alternatives fail, apply the **80% rule** over the required parameters — counting the `pass` site parameters as verified-and-matching: if ≥80% are verified-and-matching with zero failures → ⚠️ partial-verified (returned, flagged); if <80% → **`insufficient verification`**, an unverifiable reject labelled distinctly "לא נפסל על פרמטר — נדרש אימות ב-datasheet שלא היה נגיש; כדאי לשקול פנייה ליצרן" — never conflated with a real parameter failure.

> The former "every specified parameter clear on the site → ⚠️ `not datasheet-verified`" branch is gone. That case now ends at **Step 0 case 2 as ✅**, before any datasheet is attempted — the datasheet there is not *unchecked*, it is *not needed* — so it can never reach this logic.

## Workflow

### Step 0 — Triage the site-screen results (before any datasheet work)

The datasheet is expensive, and it is consulted **only** for what the sites could not settle — and **only** once everything the sites *could* settle has passed. So before anything else, sort the spec's parameters by the `status` discovery recorded:

1. **Any `fail` → ❌ rejected. Stop here.** A clear miss beyond the guard band is definitive: do not fetch the datasheet, do not call the runner, do not look for alternatives. Name the parameter, its site value, and the size of the miss. (Discovery normally rejects these at its own screen, so a `fail` reaching you is unusual — but it is terminal here too.)
2. **Every spec parameter `pass` → ✅ full match. Stop here.** The sites answered the entire spec beyond the guard band, so nothing is left to establish: **the datasheet is never opened and the runner is never called.** Return the part with `verdict: "match"`, and in your reason name each parameter with its site value, its source, and its margin, and state that no datasheet was needed.
3. **Otherwise → build the open set**: every parameter marked `borderline` or `not_stated`. Those, and only those, go to the datasheet (Step 1). A parameter marked `pass` is already verified-and-matching and is **never** re-extracted.

The 80% rule plays no part in cases 1 and 2 — it decides only among parameters that reached the datasheet and could not be confirmed there (Core definitions).

**Honest caveat for case 2:** a ✅ returned here rests on discovery's single site screen, with no second reading to diff against (Step 2 can only re-check datasheet-extracted values). Say that plainly in the reason — never imply a verification depth this path does not have.

### Step 1 — Verify the candidate against primary sources

You reach this step only with a **non-empty open set** (Step 0 case 3) — the `borderline` and `not_stated` parameters. Settle each of those against the **manufacturer's datasheet**; the `pass` parameters are already verified-and-matching and are not re-examined. The part is a match once every open parameter is confirmed as well — or, short of that, once it clears the **80% rule** (Core definitions), which decides whether a partially-verified part is still returned or is an `insufficient verification` reject.

**Reading the datasheet is ALWAYS delegated to Gemini — the skill never opens, downloads-to-read, or decodes the PDF in its own context.** Hand the datasheet to the runner (see *Reading datasheets — always via Gemini* below); it returns the extracted values as JSON, and you judge the match from them.

An open parameter is settled **only** against an actual datasheet value (what Gemini extracted) — that is precisely what `borderline` / `not_stated` mean: the site could not settle it. Distributor summaries and snippets routinely show typ at one frequency point, omit conditions, or are plain wrong, which is why a site value *inside* the guard band settles nothing here.

**Pass the runner only the open set** — the `borderline` and `not_stated` parameter names. A `pass` parameter is already confirmed and counts as **verified-and-matching** for the 80% rule; re-extracting it wastes a call and can only manufacture a disagreement about a value that was never in doubt.

For each parameter record: the actual value, whether it is min/typ/max, and any conditions (temperature, frequency point vs full band). Watch for:

- Specs guaranteed only at +25°C vs over temperature — note which.
- NF/gain at a single frequency vs across the band. The requested band must be inside the datasheet's *specified* range, not just the "operating" range.
- Column-header typos (a "Min/Typ" header on a Noise Figure column almost certainly means Max/Typ — flag, don't assume).
- Parameters listed TBD or absent → **unverified** for the 80% rule (never a match); if the whole part then falls below 80%, it is `insufficient verification`. Say "requires manufacturer contact", never guess.

Record the **margin** per parameter (e.g. OIP3 required ≥30, actual +37 → margin +7dB). Assign a verdict (see Verdicts), applying the 80% rule when not every required parameter was datasheet-confirmed.

**If the datasheet cannot be fetched** (bot-block / 409 / 404 / not indexed): follow the Access-blocked datasheet logic in Core definitions.

### Step 2 — Independent re-verification (second extraction + diff)

Reading errors are real. Since the skill never reads the PDF itself, the re-read is Gemini's too: **call the runner a second time, on the same datasheet, for the same open parameters, and diff the two JSON results.**

- **Identical → the values stand.** Note in the reason that they were confirmed by two independent extractions.
- **Any parameter differs** — a different number, a different column, one `null` and one not → **re-extract that parameter** in a third focused call. If the third agrees with one of the first two, take the majority. If all three disagree, the datasheet is not being read reliably → **downgrade that parameter to unverified** (it then falls to the 80% rule) and say so explicitly.
- **Never average two disagreeing values, split the difference, or take the more convenient one.** A discrepancy means the reading is unreliable; the honest outcome is unverified, never a chosen number.

This catches *extraction* error — two independent readings of the same source. It cannot catch a datasheet that is itself wrong or outdated.

**Also do the cheap checks that need no re-read:**

- Apply the loaded module's **physics sanity checks** to the extracted values (e.g. OIP3 is normally above OP1dB; the NF floor; gain-per-stage). A violation is a red flag → re-extract that parameter via the runner before trusting it.

**Scope — say what was and wasn't re-verified.** This step covers only parameters that came from the datasheet. A parameter confirmed from site data (`pass`) has no second reading to diff against, and a ✅ returned at Step 0 case 2 skips this step entirely. State that in the reason rather than implying a re-verification that did not happen.

### Reading datasheets — ALWAYS via Gemini (mandatory, never the skill itself)

**This is mandatory and has no fallback.** Whenever you need to read or decode data from a datasheet PDF, hand the whole job to Gemini — **never** open, download-to-read, or decode the PDF in your own context. A datasheet URL points at a **PDF file** (binary), not readable text, so its bytes must be fetched and decoded; that entire job is Gemini's, via the runner. The tools live in `tools/`:

- `config.py` — resolves the provider/model from `rf-llm.env` (Gemini by default; the single place to switch models).
- `pdf.py` + `extractor.py` — decode the PDF **in memory** and send its text to Gemini, which returns values-only JSON.
- `run_extract.py` — the single entry point that ties them together (fetch → decode in memory → Gemini → JSON). Nothing is written to disk.

**Invocation:**

```
python "${CLAUDE_SKILL_DIR}/tools/run_extract.py" --url "<datasheet URL>" --params "Gain,P1dB,NF,OIP3"
```

Pass **only the open parameters** to `--params` (Step 0 case 3). A parameter discovery marked `pass` is already confirmed — re-extracting it wastes a call and can only introduce disagreement with a value that was never in doubt.

`--file <path>` reads a local PDF instead of a URL; `--requirements-file <reqs.json>` passes the parameter names from a file instead of `--params`. It prints **one JSON object**:

```
{ success, provider, model, parameters, error, sources }
```

**`--url` and `--file` repeat — but they MERGE; they do NOT fall back.** Every URL in one call is fetched and concatenated into a single text blob for the model, and **any one fetch failing aborts the whole call**, discarding the sources that already succeeded. So repeat them only for genuinely complementary documents you expect *all* to be reachable (datasheet + errata). For **alternative sources** — mirrors, cached copies, the ampheo pattern — call the runner **once per URL, in order, until one returns `success: true`**.

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

- If the candidate **qualifies** (✅ full match, or ⚠️ partial-verified that clears the 80% rule) → the list has **exactly one** entry: `{ "model", "manufacturer", "url", "verdict" }` (the same four fields `COMPONENT_SCHEMA` defines). `verdict` is `"match"` (✅) or `"partial N/R"` (⚠️ partial-verified). The schema's third value, `"not-verified"`, belongs to the retired `not datasheet-verified` category (Outcome categories) — **do not emit it**.
- If the candidate **does not qualify** (❌ rejected, or `insufficient verification`) → the list is **empty** `[]`.

In your text (chat) output, **always state the verdict and the reason** — for a match: the per-parameter margins; for a reject: the failing parameter and its actual value, or the unverified parameters for an `insufficient verification` / access-blocked-unverifiable case. The conductor logs this text into the run's rejected list / coverage record, so it must be present even when the component list is empty.
