---
name: rf-skill-json-output
description: Parametric search for RF/microwave components (amplifiers, mixers, filters, switches, attenuators, couplers, etc.) against a multi-parameter spec, with reliable datasheet verification, returning the matching parts as Agent SDK structured output (a components list, the rf_finder Candidate shape) for the desktop GUI's AI Search — not an Excel workbook. Use whenever the user gives a component spec with electrical parameters (frequency range, gain, P1dB, OIP3, NF, insertion loss, isolation...) and wants matching parts as structured output — e.g. "מצא לי מגבר", "תחפש רכיב", "צריכה mixer", "find an amplifier 8-12 GHz gain 20dB", or pastes a spec line. Besides fully datasheet-verified matches, it ALSO returns parts that were not fully verified when at least 80% of the required parameters were verified and matched. Also use when the user asks to check "if there's anything on the market" matching parameters. The user searches AFTER already checking their 12 usual vendor sites, so those are always excluded — see the Vendor Lists section. Trigger even for short spec-only messages with no verb.
---

# RF Component Parametric Search (JSON output)

Find **every** RF/microwave component that **fully matches** a multi-parameter spec, and prove each one. The user is an RF procurement/engineering professional. This task normally takes her days of manually opening result after result; the value you add is running that sweep **completely and reliably** — faster, but never by doing less. Completeness and reliability are **both** required, and neither is traded for the other: a genuine match you **missed** and an unverified "match" you **reported** are equally worthless to her. She needs **all** the genuine matches and **only** genuine matches — bringing just a few good ones, or padding the list with unverified maybes, both fail the task. A false "match" that fails on one parameter erodes trust; a verified "no match found" is a perfectly good answer, but an unverified guess never is.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain, OP1dB, OIP3, NF, GHz, dBm) — that is how RF engineers read them.

## Required reference files

Before Step 1, load both:

- **`rf-parameter-rules.md`** — the general, component-agnostic rules for how any parameter is handled (which parameters may be filtered on, the datasheet-suitability rule, `min`/`max`/`contains` semantics, guaranteed-column-over-typ, mandatory shown conversions).
- **The per-component module matching the requested component type** (e.g. `rf-amplifier-module.md` for amplifiers) — the concrete list of searchable parameters, their units, directions, derivation formulas, fixed conventions, and physics sanity checks.

Only parameters defined in the loaded component module may be used as filters. If no module exists for the requested component type, say so and ask how to proceed rather than improvising parameters.

At **Step 4 (reporting)**, also load **`rf-json-output.md`** — the fixed schema for the structured result returned to the Agent SDK.

## Core definitions — defined once, referenced throughout

The rest of the skill refers back to this section instead of re-explaining these. Read it first.

### Verdicts

- **✅ full match** — every required parameter confirmed from the manufacturer datasheet/catalog table.
- **⚠️ borderline** — meets spec but only as typ, or exactly at the limit, or partially verified (the 80% rule below), or the access-blocked case below.
- **❌ rejected** — a required parameter fails; state which and by how much.

### Partial-verification acceptance — the 80% rule

A part need **not** have every required parameter confirmed to be returned as a good result — but the tolerance is bounded and precise. This rule decides whether a part that fell short of full datasheet verification is still returned or is excluded. Over the parameters the user actually specified (call the count **R**), classify each required parameter after Step 3:

- **verified-and-matching** — confirmed to meet the spec from a primary source: read from the manufacturer datasheet and passing (Step 3), **or** a site-checkable parameter already clear of its guard band at Step 2.7 that the efficiency rule left un-re-extracted (it counts as confirmed).
- **failed** — a datasheet value that misses the spec.
- **unverified** — neither: not stated on the datasheet, TBD, a datasheet-only parameter that could not be read, or a parameter left unconfirmed because the datasheet was inaccessible.

Decision (apply in order):

1. **Any failed parameter → ❌ rejected.** The 80% rule never rescues a real miss; a datasheet value that loses against the spec rejects the part as before.
2. **All R verified-and-matching, none unverified → ✅ full match** (per Verdicts).
3. **0 failed and (verified-and-matching ÷ R) ≥ 0.80 (but not all) → ⚠️ partial-verified** — returned as a good result. Emitted to the JSON and placed in the matches table, flagged **"אומת חלקית — N/R פרמטרים אומתו"**, naming the unverified parameters.
4. **0 failed and (verified-and-matching ÷ R) < 0.80 → excluded** — not a good result. Goes to the rejected list / coverage as `insufficient verification`, listing which required parameters are unverified. **Not** emitted to the JSON, and **not** a parameter failure — never conflated with a ❌.

The ratio is computed over required (user-specified) parameters only; parameters the user did not specify are never counted in **R**. This rule makes precise the otherwise-vague "one spec unverifiable" case: the exact gate is 80% verified-and-matching with zero failures.

### site-checkable vs datasheet-only

The loaded component module classifies each parameter as **site-checkable** (reliably shown/filterable on parametric sites and catalog tables) or **datasheet-only** (reliably found only on the datasheet). This classification drives every screen/verify decision below.

### The site-data rule (promote-only, except one gate)

Site data (search snippets, distributor/parametric tables) may **freely add or promote** a candidate, but may **reject** one **only** at the Step 2.7 screen, and only via a catalog fact or a clear miss on a site-checkable parameter the site actually exposes. Site data cannot *confirm* a match (typ-at-one-frequency, missing conditions, plain errors) — which is also why it cannot fail a *borderline* one. Everything not cleanly rejected at 2.7 becomes a **plausible candidate** whose datasheet must be opened. **Never silently skip or drop a source** in any step — an empty/blocked source is logged, not omitted.

### Outcome categories (used in the coverage statement and audit)

- `checked/no candidates` · `checked/found X` · `not covered`
- **`rejected at site screen`** — dropped at Step 2.7 on a clear miss on a site-exposed parameter (or a catalog fact), logged with the failing site parameter and its value. A definitive rejection; **not** flagged "not datasheet-verified". Not opening the datasheet of a part that already failed on the site is expected, not a gap.
- **`not datasheet-verified`** — passed **every** specified site-checkable parameter at 100% (clear of the guard band) yet the datasheet was not checked (the access-blocked ⚠️ case below). The **only** access-blocked outcome that carries this flag.
- **`insufficient verification`** — reached datasheet-check with zero outright failures, but fewer than 80% of the required parameters ended verified-and-matching (the 80% rule). Excluded from the results, logged with the unverified parameters. **Not** a parameter failure, and **not** the same as `not datasheet-verified`.
- **`datasheet inaccessible`** — the datasheet could not be fetched; log the alternative sources tried and whether the part ended as a ⚠️ not-verified match or an unverifiable reject.

### Access-blocked datasheet logic (referenced by Steps 3, 3.5, 4, 5)

A blocked datasheet is an *access* failure, never a parameter failure. First **exhaust alternative datasheet sources, logging each one tried**: everything.rf's linked/mirrored datasheet, a search-engine cached copy, a distributor-hosted PDF, and the `resources.ampheo.com/static/datasheets/<vendor>/<part>.pdf` mirror pattern. Only if **all** fail, classify by the module:

- **Every** specified parameter is site-checkable, was actually shown on a site, and clears the spec **beyond** its guard band (merely inside the guard band ≠ clear) → **⚠️ match, `not datasheet-verified`**. Sits in the returned matches (JSON, with `source: "table"` and an aggregator link as `url`; and the matches table) with the flag "לא אומת — גישה ל-datasheet חסומה". **Never** shown as ✅. This is the one case where site data may seat a part in the matches output.
- **Otherwise** (some specified parameter is datasheet-only, or is site-checkable but was never shown on a site, or passed only *within* its guard band) → apply the **80% rule** (above) over the required parameters, counting the site-checkable ones clear beyond their guard band as verified-and-matching: if ≥80% are verified-and-matching with zero failures → ⚠️ partial-verified (returned, flagged); if <80% → **`insufficient verification`**, an unverifiable reject that goes to the rejected list labelled distinctly "לא נפסל על פרמטר — נדרש אימות ב-datasheet שלא היה נגיש; כדאי לשקול פנייה ליצרן" — never conflated with a real parameter failure.

## Workflow

### Step 1 — Parse the spec, then clarify ONCE before searching

Extract every parameter into a requirements table: name, value, direction (min/max/range), and whether it's hard or soft. Specs arrive as terse free text ("pidb 20 min, OIP3 30dbm, NF 6db max").

Ambiguities are the #1 source of wrong results. Before searching, ask the user (in one round, using the question tool if available) only about what is genuinely ambiguous:

- **Frequency**: must the part's band merely contain the requested range (usual), or match it exactly?
- **Two-sided ranges** (e.g. "gain 20-30dB"): is the upper bound hard (a part with 33dB is rejected) or advisory?
- **min/typ/max**: do required values need to be guaranteed (min/max columns) or is typical acceptable?
- **Form factor**: MMIC/SMT, connectorized module, bare die — or anything?

Do NOT re-ask things already answered in the conversation, and don't ask about parameters that are already unambiguous. Known user defaults: band containment is fine; typical values acceptable; any form factor.

### Step 2 — Search wide (candidates), never trusting search snippets

Discovery must not hang on any single list of vendors. A small vendor that a hand-maintained list omits **and** Google indexes poorly falls through both nets and is missed entirely — this is exactly how Aelius Semiconductors' ASL 4020 / ASL4065 were missed on a real query ("amplifier 14–15 GHz, Gain≥20 dB, P1dB≥24 dBm"), even though everything.rf lists Aelius with 111 amplifiers. So run **three independent discovery paths** and pool everything they surface into one candidate queue. **Dedupe the queue** (same vendor/part surfaced by more than one path is processed once) before it flows into the Step 2.7 screen. A vendor is missed only if **all three** paths miss it — and even then the report says so honestly (Step 4).

These paths are component-agnostic: the category and category hints vary by component type, the mechanism does not. In every path, **always exclude the user's 12 vendor domains** using blocked_domains (Vendor Lists section). Per the site-data rule, a hit from any path is only a *candidate* until Step 3.

**Path A — Parametric aggregator query (operate the filters; do NOT keyword-search).**

**The Path A search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full coverage:** page through **every** result page on all four aggregators; never stop at the first page or a partial view. Record how many pages/results each site returned. If a site paginates, lazy-loads, or caps results, exhaust it to the end — a result the filter admits but that sits on page 7 is missed only because you stopped early.
- **Precise — filter accuracy:** operate each site's **own parametric engine**, and set **every** `site-checkable` parameter from the current spec — each in the right direction (min/max/range) and with its guard band. Never keyword-search these domains and never trust a snippet, a summary card, or a category label in place of the real filtered value.
- **Reliable — failure transparency:** if any of the four sites is blocked, returns empty, times out, or lacks a filter the spec needs, **say so explicitly** in the coverage statement — never silently skip. A site that was not fully covered is named as not covered, with the reason; "0 results" and "could not reach the site" are different outcomes and must not be reported as the same thing.

Path A runs against a **fixed, closed set of aggregators — and only these four**. It never visits an individual manufacturer's own site, and no other aggregator is added to this path:

- **everything.rf** — the best RF-specific parametric DB
- **Mouser**
- **Digi-Key**
- **Octopart**

On each, drive the site's *own parametric/filter engine* (not a keyword box): pick the component category for **this** query (Amplifiers, Mixers, Filters, LNAs, …), set the numeric filters from the current spec (whichever parameters the loaded module marks site-checkable), and **page through ALL result pages**. This is a *category-wide* sweep filtered by the current spec — never a search for a pre-named part; return every part the filters admit. A keyword web-search against these domains is **NOT** a substitute for their parametric engine: it reproduces the indexing weakness that caused the Aelius miss above. Do not add any other aggregator to Path A — vendor discovery beyond these four happens in Paths B and C, not here.

**Path B — Part-graph traversal (vendor DISCOVERY through parts, not names).**

**The Path B search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full traversal:** run **all four** derived-search types on **every** candidate (alternatives/equivalent/cross-reference; sibling parts in the family; the aggregator's "similar products" block; and a re-run in the found parts' vocabulary). Then keep looping wave after wave — each new vendor spawns its own derived searches — until a full wave surfaces no new vendor and no new plausible candidate, up to the 3-wave ceiling. Never stop after one search type, one candidate, or one wave.
- **Precise — correct traversal:** correctly recognize when a competing part comes from a vendor **not yet seen this session**, and when it does, actually sweep that vendor's catalog for the category — don't just note the name. Follow sibling families to their neighbors, and match each found part's **real vocabulary** rather than forcing one fixed term.
- **Reliable — honest coverage:** record **every** vendor the traversal discovers (these also grow the cache for Path C). If the loop stops at the 3-wave ceiling rather than because a wave ran dry, **say so explicitly** in the coverage statement — a ceiling-truncated traversal may have missed vendors and must never be presented as exhaustive.

One good candidate is a thread to pull; its purpose is to surface **new vendors no list or directory contains** — found through parts, not names. From every confirmed or plausible candidate, run derived searches:

- "alternatives to <part number>" / "<part number> equivalent" / "cross reference"
- sibling parts in the same family (a vendor with an ARF1211 likely has ARF12xx neighbors — check the vendor's category page)
- each aggregator's "similar products" section on the candidate's page
- re-run the best query in the found parts' vocabulary ("driver amplifier" vs "gain block" vs "medium power amplifier").

Whenever a competing part comes from a **vendor not yet seen this session**, add that vendor and sweep its catalog for the category. **Loop until a wave surfaces no new vendors and no new plausible candidates, up to a ceiling of 3 waves** (or stop earlier once a wave adds nothing) — then continue; note the ceiling in the coverage statement if it was hit.

**Path C — Cache sweep.**

**The Path C search must be deep, precise, and reliable — this is the standard the entire path is held to, not a slogan:**
- **Deep — full sweep:** check **every** vendor in the cache relevant to the component category — not a sample, not just the ones that look likely. For each, actually open its catalog (site search or catalog PDF) and filter for the category; a vendor skipped because it "probably has nothing" is exactly how a match is missed.
- **Precise — correct access:** use the access method the cache records for each vendor (site search / catalog URL / PDF pattern). If a catalog PDF returns empty, do not accept that as "no parts" — it is probably scanned/image or bot-blocked, so fall back to the vendor's HTML pages or everything.rf's mirrored copy before concluding.
- **Reliable — honest coverage:** log **every** vendor swept, **including** those that returned nothing (`checked/no candidates`) — never omit an empty vendor. A vendor whose catalog was blocked, empty, or unreachable is named with the reason, never silently skipped; "no matching parts" and "could not read the catalog" are different outcomes.

Sweep the manufacturers in the vendor cache (Vendor Lists) relevant to the component category, checking their catalogs directly (site search or catalog PDF fetch). The cache is **not** the definition of which vendors exist — Paths A and B are; the cache only makes access to a *known* vendor cheap. If a catalog PDF returns empty, it is probably scanned/image or bot-blocked — say so and try the vendor's HTML pages or everything.rf's copy instead (per the site-data rule: never silently skip).

**Grow the cache.** Whenever Path A or Path B surfaces a vendor not already in the cache, append it there with the access metadata learned (domain, catalog URL, parse/access notes, component categories). The cache grows automatically toward completeness for the categories searched; no human maintains it.

### Step 2.7 — Site-level pre-screen (Stage 1: cheap filter before any PDF)

Datasheet fetches are the expensive part. Before opening any datasheet, screen candidates using only the data the sites expose — no PDF. The screen uses only the *site-checkable* parameters the query actually specified (see `rf-parameter-rules.md` for mechanics and tolerance):

1. On each site, see which of those query parameters it can filter on or shows in its table.
2. Compare each to the query, using the semantics/tolerance in `rf-parameter-rules.md`.
3. **Passes** when every site-checkable query parameter the site exposes matches → promoted to Step 3.
4. **Rejected at Stage 1** only when a site-exposed parameter clearly fails or a catalog fact rules it out (band that cannot contain the request, wrong type/form factor, excluded vendor).

Safety rules (all generic in `rf-parameter-rules.md`): parameters the user did not specify or not in the module are ignored (treated as a match); a datasheet-only parameter is never screened here; a site-checkable parameter the site does not expose cannot reject the part (promote, confirm at datasheet); **when in doubt, promote** — Stage 2 catches borderline parts.

**Log every Stage-1 reject** as `rejected at site screen` (see Outcome categories) — the clean-rejection case, **not** "not datasheet-verified".

### Step 3 — Verify every candidate against primary sources

A candidate becomes a match only after every required parameter is confirmed against the **manufacturer's datasheet** — or, short of that, after it clears the **80% rule** (Core definitions), which decides whether a partially-verified part is still returned or is an `insufficient verification` reject. **Reading the datasheet is ALWAYS delegated to Gemini — the skill never opens, downloads-to-read, or decodes the PDF in its own context.** Whenever a candidate's datasheet must be read, hand it to the runner (see *Reading datasheets — always via Gemini* below); it returns the extracted values as JSON, and the agent judges the match from them. Distributor summaries and snippets routinely show typ at one frequency point, omit conditions, or are wrong — see the site-data rule: a part is rejected here only against an actual datasheet value (what Gemini extracted from the datasheet); site data may only have promoted it in.

**Efficiency:** extract only the parameters still open. A site-checkable parameter that already cleared the spec **beyond its guard band** at Step 2.7 need not be re-extracted — pass the runner only the datasheet-only and borderline parameter names. (Such a guard-band-clear site parameter counts as **verified-and-matching** for the 80% rule.)

For each parameter record: the actual value, whether it is min/typ/max, and any conditions (temperature, frequency point vs full band). Watch for:

- Specs guaranteed only at +25°C vs over temperature — note which.
- NF/gain at a single frequency vs across the band. The requested band must be inside the datasheet's *specified* range, not just the "operating" range.
- Column-header typos (a "Min/Typ" header on a Noise Figure column almost certainly means Max/Typ — flag, don't assume).
- Parameters listed TBD or absent → **unverified** for the 80% rule (never a match); if the whole part then falls below 80%, it is `insufficient verification`. Say "requires manufacturer contact", never guess.

Record the **margin** per parameter (e.g. OIP3 required ≥30, actual +37 → margin +7dB) so the user can rank matches. Assign a verdict (see Verdicts), applying the 80% rule when not every required parameter was datasheet-confirmed.

**If the datasheet cannot be fetched** (bot-block / 409 / 404 / not indexed): follow the Access-blocked datasheet logic in Core definitions.

### Step 3.5 — Independent re-verification (not run in the current Gemini-reads mode)

Reading errors are real, and normally this step re-reads each ✅/⚠️ candidate's datasheet from scratch to catch them. That mechanism relied on two things this configuration removes — the agent (or a subagent) **re-reading the PDF**, and re-checking each value's **quoted string + location**. Both are disabled here (datasheet reading is always Gemini's, and no quote/location is captured), so **independent re-verification is not performed**: a reported match rests on Gemini's single extraction. Note this plainly in the coverage statement.

**Still do the cheap checks that need no re-read:**

- Apply the loaded module's **physics sanity checks** to Gemini's extracted values (e.g. OIP3 is normally above OP1dB; the NF floor; gain-per-stage). A violation is a red flag → re-extract that parameter via the runner before trusting it.
- A ⚠️ **access-blocked** match (datasheet unreachable, site values clear of the guard band) is re-checked against the *site* values only — re-run the parametric query fresh and confirm each still clears the spec beyond its guard band — and stays ⚠️ `not datasheet-verified`.

**To restore a real trust layer later** without breaking the rules, re-enable this step as a **second, independent Gemini extraction**: call the runner again on the same datasheet and diff the two JSON results; any discrepancy → re-extract and resolve, or downgrade to ⚠️.

### Reading datasheets — ALWAYS via Gemini (mandatory, never the skill itself)

**This is mandatory and has no fallback.** Whenever Step 3 needs to read or decode data from a datasheet PDF, the skill hands the whole job to Gemini — it **never** opens, downloads-to-read, or decodes the PDF in its own context. A datasheet URL points at a **PDF file** (binary), not readable text, so its bytes must be fetched and decoded; that entire job is Gemini's, via the runner. The tools live in `tools/`:

- `config.py` — resolves the provider/model from `rf-llm.env` (Gemini by default; the single place to switch models).
- `pdf.py` + `extractor.py` — decode the PDF **in memory** and send its text to Gemini, which returns values-only JSON.
- `run_extract.py` — the single entry point that ties them together (fetch → decode in memory → Gemini → JSON). Nothing is written to disk.

**Invocation — call the runner per candidate:**

```
python tools/run_extract.py --url "<datasheet URL>" --params "Gain,P1dB,NF,OIP3"
```

`--file <path>` reads a local PDF instead of a URL; `--requirements-file <reqs.json>` passes the parameter names from a file instead of `--params`. It prints **one JSON object**:

```
{ success, provider, model, parameters, error, sources }
```

`parameters` maps each requested name to `{unit, min, typ, max, value, condition}` or `null` (not stated on the datasheet). Exit code 0 = success, 1 = failure. A `success:false` is a fetch/read failure → apply the **Access-blocked datasheet logic** (Core definitions); never a silent match or reject.

**First action:** confirm the config — `RF_LLM_PROVIDER`, `RF_LLM_MODEL`, and the provider key are set in `tools/rf-llm.env`, and the provider is registered in `extractor._get_runtime` (currently `mock` / `local` / `openai` / `gemini`). If the config is missing or broken, **say so and stop** — there is no "read the PDF yourself" fallback.

**Gemini extracts; the skill judges.** The model returns values only — no verdict. The agent maps the JSON onto `rf-parameter-rules.md` + the component module, computes margins, and assigns ✅/⚠️/❌ (applying the 80% rule for a part not fully datasheet-confirmed):

- `min` / `typ` / `max` → for a `min` or `max` parameter, compare against the **guaranteed column** the direction needs (the `min` field for a `min` parameter, the `max` field for a `max` one); use `typ` **only** when the guaranteed column is `null`, then mark the verdict ⚠️ "typ only". For a `contains` parameter (frequency band, temperature range), the range comes back as `min`..`max` — check that range **fully contains** the requested one.
- `null` (parameter not stated) → the datasheet-suitability rule applies: this parameter is **unverified** for the 80% rule (reject the *part* only if it then falls below 80% — never guess a value the model returned as `null`).
- `value` → **only** categorical/discrete parameters (MSL, package type, size string) and explicitly-enumerated discrete supply lists — numeric ranges live in `min`/`max`, not here.
- `condition` → the operating point; for a band-dependent parameter, confirm the returned value covers the **requested band**. The extractor returns one object per parameter, so a multi-band part may need a focused re-extraction at the requested band.
- Compute and **show** each margin and unit conversion (`2 W → +33.0 dBm; required ≥ +30 dBm; margin +3.0 dB`).

State in the coverage statement that datasheet reading was done via Gemini, and which provider/model.

### Step 4 — Report: chat table + structured result

**Chat**: one table of matches/borderlines (part number, vendor, band, each required parameter with min/typ noted, verdict), followed by a short "checked and rejected" list — part, failing parameter, actual value. Placement follows the Outcome categories: a ⚠️ access-blocked match belongs in the matches table with its "לא אומת — גישה ל-datasheet חסומה" flag (never in the rejected list); a ⚠️ partial-verified match (the 80% rule) belongs in the matches table flagged "אומת חלקית — N/R פרמטרים אומתו", naming the unverified parameters; an access-blocked *unverifiable* part and an `insufficient verification` part (<80%) go in the rejected list, each marked distinctly ("לא נפסל על פרמטר — כדאי לשקול פנייה ליצרן") — never as a parameter failure. The rejected list is what convinces the user the search was real.

**Structured result** — the skill's **final answer** is the structured result defined in **`rf-json-output.md`** (load that file now): a single JSON object `{ "components": [ ... ] }`, one entry per **returned** component, with `model`/`manufacturer`/`url`/`verdict` plus (recommended) `source` and `params{canonical -> {value, unit}}`. It is **returned to the Agent SDK** (`ResultMessage.structured_output`) — **nothing is written to disk**. The desktop GUI's AI Search renders it straight into its table (that path does **not** re-verify through `rf_finder`'s Python verifier — the `verdict` you set is shown as-is). The `components` list holds exactly the parts that qualify as good results:

- ✅ full matches → `verdict: "match"`.
- ⚠️ `not datasheet-verified` access-blocked matches → `verdict: "not-verified"`, `source: "table"`, aggregator link as `url`.
- ⚠️ partial-verified matches that clear the 80% rule → `verdict: "partial N/R"` (N of R required params verified).

Everything excluded — datasheet ❌, `rejected at site screen`, access-blocked *unverifiable*, and `insufficient verification` (<80%) — is **not** in `components`; it appears only in the streamed chat rejected list and the coverage journal below. Values in `params` carry the raw unit as found (no normalization), omit any parameter not found, and every returned component has at least one primary RF parameter (full rules in `rf-json-output.md`).

**Emit each result live (do not wait for the end).** The moment a component is confirmed as a good result (a ✅ / ⚠️ that qualifies), print it **immediately on its own line**, using **exactly the SDK schema fields** — `model`, `manufacturer`, `url`, `verdict` (the same four `COMPONENT_SCHEMA` defines; no `params`/`source` here):

```
@@RESULT@@ {"model": "...", "manufacturer": "...", "url": "...", "verdict": "match"}
```

One compact JSON object per line, prefixed by the exact marker `@@RESULT@@`. The caller parses these lines to show results as they are found and lets the user stop the run early once she has enough. This is **in addition to** the final `{ "components": [ ... ] }` answer, which remains the authoritative, complete, deduplicated list — emit each qualifying part once as it is confirmed, then still include all of them in the final answer.

The proof-of-work the Excel workbook used to carry in its נבדקו ונפסלו and יומן כיסוי sheets now lives entirely in the **streamed chat report** (the rejected list and the coverage journal below) — nothing is dropped, only moved out of a file and into the run's progress text, exactly as thorough as before. (The GUI discards this progress and shows only the returned `components`; a chat/Claude-Code run shows the full report.) This proof-of-work is not decoration — it IS the product: a components list with no rejection/coverage record is unverifiable, and the user will re-check everything by hand.

**One-match warning**: 0–1 matches after a real sweep is possible but suspicious. Before accepting, run at least one more Path B wave and confirm all three paths (A/B/C) ran for this category — then report, saying explicitly in the coverage statement that this was done.

**End with an honest coverage statement**: which of the three paths ran and their outcomes; which sources were fully swept vs only sampled; whether "no match" means "none exists" or "none found in sources covered"; and that datasheet reading was delegated to Gemini (provider/model), with no independent re-verification run. Coverage is bounded by what these sources contain — state plainly that a vendor absent from **every** path may still be missed; keep the residual gap visible, never disguised as a clean "no match". If nothing matches, show the nearest misses with their exact gaps (a 2dB gap is actionable — she may relax the spec).

**Coverage journal (in chat — formerly Excel sheet 3).** Include the manufacturers/sources table as a chat table — one row per vendor or source touched at least once through any path, identical format for all, with columns: **יצרן / מקור** · **נבדק דרך** (A/B/C) · **שאילתה שנשלחה** (the real query per checked source — keyword string, Path-A filter set, or catalog term/URL; empty only for a `not covered` source) · **תוצאה** (an Outcome category) · **קישור**. It must be:

- **Exhaustive** — a vendor that returned nothing is listed `checked/no candidates`, **never omitted**; searched-and-empty is as important as a match.
- **Aggregators expanded, never collapsed** — a Path-A parametric engine adds **one row per vendor it surfaced**, each in the same format. A single "everything.rf — 426 amps" row is not acceptable (the aggregator may *additionally* keep one summary line in the paths summary). A vendor surfaced only inside an aggregator gets the outcome the aggregator data gives it.

Also give the short **paths summary** (one line per discovery path A/B/C with its run outcome, e.g. "everything.rf parametric ✓ — N pages"; "part-graph traversal ✓ — M waves, K new vendors"; "cache sweep ✓") and the note that datasheet reading was via Gemini (provider/model) with no independent re-verification.

### Step 5 — Final audit before sending

Run this checklist; fix anything that fails before reporting. (Each item points back to the rule it enforces.)

- [ ] Every ✅/⚠️ part: every required parameter has an actual value, min/typ/max label, margin, and a working datasheet/catalog link — **or**, for a ⚠️ access-blocked match, site values with guard-band-clear margins, an aggregator link, and the "not verified" flag; for a ⚠️ partial-verified match, the verified parameters have values and margins and the unverified ones are named.
- [ ] Every ⚠️ partial-verified part clears the **80% rule**: zero failed required parameters, ≥80% verified-and-matching, with the unverified parameters named. Every part below 80% is an `insufficient verification` reject — not a match, and not a ❌.
- [ ] The coverage statement states that datasheet reading was delegated to Gemini (provider/model) and that no independent re-verification was run (current Gemini-reads mode).
- [ ] Every datasheet ❌ rests on an actual datasheet value — never on snippet evidence. The only non-datasheet entries in the rejected list are `rejected at site screen`, access-blocked *unverifiable*, and `insufficient verification` parts, each labelled per the Outcome categories.
- [ ] `rejected at site screen`, `not datasheet-verified`, and `insufficient verification` used exactly per the Outcome categories (not conflated).
- [ ] Any inaccessible datasheet followed the Access-blocked logic: alternatives tried and logged, then classified as ⚠️ not-verified match, ⚠️ partial-verified (80% rule), or unverifiable reject. Never auto-dumped into rejected, never shown as ✅.
- [ ] Every ❌ part names the specific failing parameter and its actual value (except access-blocked unverifiable / insufficient verification, which name the datasheet-only parameter(s) they couldn't check and flag "consider contacting the manufacturer").
- [ ] No part is from an excluded vendor (including legacy brands now on excluded domains).
- [ ] All three paths ran; the coverage statement reports each outcome (A pages paged; B waves + new vendors, and whether the 3-wave ceiling was hit; C cache sweep). A skipped path is named, not silently omitted.
- [ ] The coverage statement states plainly that coverage is bounded by these sources and a vendor absent from every path may still be missed.
- [ ] Any vendor newly discovered by Path A/B was appended to the vendor cache with access metadata.
- [ ] The Step 1 clarifications are reflected (e.g. a hard bound → no match exceeds it).
- [ ] The module's sanity checks were applied to Gemini's extracted values; any violation was re-extracted via the runner.
- [ ] The structured result validates against `rf-json-output.md`: a `{ "components": [...] }` object; each entry has `model`/`manufacturer`/`url`/`verdict` (plus `source`/`params` when set); canonical parameter keys only; raw units (no normalization); parameters omitted when not found; at least one primary RF parameter per returned component. It is returned to the SDK (not written to disk).
- [ ] `components` holds **exactly** the good results — ✅ (`match`), ⚠️ access-blocked `not datasheet-verified` (`not-verified`), and ⚠️ partial-verified (`partial N/R`) — and **excludes** every ❌, `rejected at site screen`, access-blocked *unverifiable*, and `insufficient verification` part. The parts and verdicts in `components` match the streamed matches table exactly.
- [ ] The coverage journal is present in chat: **exhaustive** (every touched vendor, including empty ones), Path-A aggregators **expanded** into per-vendor rows, with the **"שאילתה שנשלחה"** real query per checked source.
- [ ] If 0–1 matches: an extra Path B wave was run and the coverage statement says so.

## Efficiency notes

- Two-stage search — cheap wide search → **Step 2.7 site screen** → datasheet fetches for survivors only — is the main token saver. Datasheets open only for parts that pass the screen.
- **Dedupe the candidate queue** (Step 2) before Step 2.7 so a vendor/part surfaced by multiple paths is processed once.
- At Step 3, only ask the runner to extract the datasheet-only and borderline parameters — a site-checkable parameter already clear of its guard band at 2.7 needn't be re-extracted.
- Step 3.5 independent re-verification is off in the current Gemini-reads mode (see Step 3.5), so no extra tokens are spent there.
- If the user names a vendor missing from the cache, add it (Path C) for the session with whatever access metadata you learn — same auto-append rule Paths A/B use.

## Vendor Lists

### ALWAYS EXCLUDE — the user's 12 pre-checked sites

The user checks these manually before every search. Pass all of them in blocked_domains on every web search, and never present parts from them:

| Vendor | Domain |
|---|---|
| Mini-Circuits | minicircuits.com |
| Qorvo (incl. Custom MMIC, Sirenza legacy parts) | qorvo.com |
| MACOM (incl. Mimix legacy) | macom.com |
| Analog Devices (incl. Hittite legacy) | analog.com |
| UMS | ums-rf.com |
| 3R Waves | 3rwave.com |
| AMCOM | amcomusa.com |
| VectraWave | vectrawave.com |
| Guerrilla RF | guerrilla-rf.com |
| Microchip | microchip.com |
| Marki Microwave | markimicrowave.com |
| RW MMIC | rwmmic.com |

Legacy-brand note: parts whose datasheets now live on an excluded domain (e.g. Custom MMIC → qorvo.com, Hittite → analog.com) count as excluded.

### VENDOR CACHE — access knowledge for known manufacturers

This is a **cache**, not the source of truth for which vendors exist. The universe of vendors is defined by Path A (parametric aggregators) and Path B (part-graph traversal); this list's only job is to make access to an *already-known* vendor cheap and reliable — per-vendor access metadata (domain, catalog URL, parse/access notes, category hints). Path C sweeps it. Generic web search misses many of these (poor indexing), so checking their catalogs directly still matters — but absence here no longer means a vendor won't be found.

The cache is **self-growing** — no human maintains it:

- Whenever Path A or Path B discovers a vendor NOT listed here, append it with the access metadata learned (domain, catalog URL, parse/access notes, component categories).
- The cache MAY be seeded or refreshed from **everything.rf's Companies directory** for the relevant category.
- Not every vendor is relevant to every part type — use the category hints.

**MMIC / semiconductor:**
- Aelius Semiconductors — aeliussemi.com (amps: LNA, gain block, GaN power to 25W, X/Ku-band; catalog at products.php?slug=amplifiers; datasheets at /admin/uploads/<digits><PART>.pdf; ~118 amps; **poorly keyword-indexed — sweep the catalog directly**. Distributed via astramwp.com)
- Altum RF — altumrf.com (amps, X/Ku-band; also stocked at rellpower.com; **per-part datasheets are request-gated — use altumrf product pages + rellpower/expocad catalog PDFs for site-level specs**)
- BeRex — berex.com (amps, LNAs)
- CEL (California Eastern Labs) — cel.com (LNAs, discrete)
- Skyworks — skyworksinc.com (amps < ~6 GHz, switches, mixers)
- NXP — nxp.com (power, drivers)
- Wolfspeed — wolfspeed.com (GaN power)
- Ampleon — ampleon.com (power)
- Broadcom/Avago legacy MMICs — broadcom.com
- Mercury Systems / Atlanta Micro — mrcy.com (AM-series amps)

**Connectorized modules / hybrid amplifiers:**
- Ciao Wireless — ciaowireless.com (very broad amp catalog; catalog PDFs parse well)
- Narda-MITEQ (L3Harris) — nardamiteq.com (huge AMF amplifier catalog — poorly indexed, sweep directly. **Part numbers encode the spec**: `<TYPE>-<class>-<FminFmaxMHz>-<gain>-<P1dB>P` e.g. AMF30-12001800-60-30P = 12-18 GHz, 60 dB, +30 dBm P1dB — screen straight off the model number. LNA datasheets resolve at /docs/<MODEL>.PDF; AMF/medium-power per-part PDFs often behind viewmodel.php→"Contact Factory" and /docs guesses 404. Medium-power line OP1dB 26-33 dBm)
- Erzia — erzia.com
- B&Z Technologies — bnztech.com
- Planar Monolithics Industries (PMI / Quantic) — pmi-rf.com (broad PA catalog; power-amplifiers category lists guaranteed **min gain + Psat** but often **not OP1dB**; datasheet PDFs are **image-only/scanned** — Gemini runner returns "No text extracted", and the Richardson RFPD mirror 403s. For power parts OP1dB usually needs a factory request. Model encodes freq/gain/NF/Psat, e.g. PA-2G18G-43-5-40-SFF = 2-18 GHz, 43 dB, Psat 40 dBm/10W)
- Cernex / CernexWave — cernex.com
- Wenteq Microwave — wenteq.com (store.wenteq.com has per-part pages)
- Pasternack — pasternack.com (site bot-blocked; datasheets mirrored at resources.ampheo.com/static/datasheets/pasternack/<part>.pdf)
- Fairview Microwave — fairviewmicrowave.com
- Lotus Communication Systems — lotussys.com
- AML — amlj.com
- Elite RF — eliterfllc.com
- Triad RF — triadrf.com
- Spacek Labs — spaceklabs.com (mm-wave)
- Quantic brands (X-Microwave, PMI, Corry...) — catalog.xmicrowave.com

**Path A aggregators — the fixed, closed set (only these four; no other aggregators):**
- everything.rf — best RF-specific parametric DB; also mirrors specs of poorly-indexed vendors
- Mouser, Digi-Key — parametric filters for SMT/MMIC parts
- Octopart — cross-manufacturer part-search aggregator

This cache is the accumulated institutional knowledge of the search — Paths A and B grow it automatically over time.
