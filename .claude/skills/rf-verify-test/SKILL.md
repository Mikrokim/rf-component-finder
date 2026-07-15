---
name: rf-verify-test
description: OFFLINE TEST TWIN of rf-verify. Verifies ONE already-discovered candidate against a multi-parameter spec using the SAME matching logic as rf-verify — per-parameter comparison, margins, min/max/contains semantics, and the 80% partial-verification rule, returning match / partial / not-verified / rejected — but reads the candidate's parameter values from the LOCAL JSON dataset (mockdata/path_{a,b,c}.json) instead of a datasheet via Gemini. No datasheet fetch, no Gemini, no web, no Bash. Used only when the conductor runs in RF_SKILL_MODE=test, one run per candidate that rf-discovery-test surfaces. Pair with rf-discovery-test.
---

# RF Component Verification — TEST MODE (single candidate, local JSON)

This is the **offline test twin** of `rf-verify`. Its job and judgment are
**identical** to the real skill — verify **one** candidate against the spec and
**prove** the verdict, applying the full comparison logic and the 80% rule — with
exactly **one** difference, marked below: the candidate's parameter values are
read from a **fixed local JSON dataset** instead of from its datasheet via Gemini.
You do **not** search for other parts; a conductor runs you once per candidate.

## Input

The caller gives you the **candidate** (`model`, `manufacturer`, `url`) and the
**spec** (the requested parameters, each with value + direction). Verify that
candidate against that spec. Nothing else is in scope.

## DATA SOURCE (test mode) — the one and only change vs. rf-verify

**You must never fetch a URL, open a datasheet, call Gemini, or run a web search.**
The candidate's parameter values come from the same three JSON files discovery
read, at the repository root (your working directory):

- `mockdata/path_a.json`, `mockdata/path_b.json`, `mockdata/path_c.json`

Each is `{ "components": [ { "model", "manufacturer", "url", "params": {…} }, … ] }`.

**Look up the candidate:** read the files (with `Read`) and find the entry whose
`model` (and `manufacturer`, when given) matches the candidate. Its `params`
object — canonical amplifier keys (`freq_range`, `Gain`, `P1dB`, `NF`, `IP3`, …)
with unit-bearing string values — **is** your source of truth, exactly where the
real skill would use Gemini's extracted datasheet values. In test mode each
parameter is a **single stated value** (treat it as the guaranteed datasheet
value; there is no separate min/typ/max column). A parameter **absent** from the
entry's `params` is the test-mode equivalent of "not stated on the datasheet" →
**unverified** for the 80% rule. If the candidate is in none of the files, you
cannot verify it → return an empty components list and say so.

## Report language

Report in Hebrew. Keep parameter names, part numbers and units in English (Gain,
OP1dB, OIP3, NF, GHz, dBm).

## Required reference files

Before verifying, load both:

- **`rf-parameter-rules.md`** — the general parameter-handling rules (`min`/`max`/
  `contains` semantics, guaranteed-value comparison, mandatory shown conversions).
- **The per-component module** matching the candidate's type (e.g.
  `rf-amplifier-module.md` for amplifiers) — the parameters, units, directions,
  derivation formulas, and physics sanity checks.

Only parameters defined in the loaded module are checked. If no module exists for
the component type, say so and stop.

## Core definitions

### Verdicts

- **✅ full match** — every required parameter confirmed from the entry's params.
- **⚠️ borderline** — meets spec but only marginally / partially verified (the 80%
  rule below).
- **❌ rejected** — a required parameter fails; state which and by how much.

### Partial-verification acceptance — the 80% rule

A part need **not** have every required parameter confirmed to be returned — but
the tolerance is bounded. Over the parameters the spec specified (count **R**),
classify each after comparison:

- **verified-and-matching** — the entry states the parameter and it passes.
- **failed** — the entry states the parameter and it misses the spec.
- **unverified** — the entry does **not** state the parameter (absent from
  `params`).

Decision (apply in order):

1. **Any failed parameter → ❌ rejected.** The 80% rule never rescues a real miss.
2. **All R verified-and-matching, none unverified → ✅ full match.**
3. **0 failed and (verified-and-matching ÷ R) ≥ 0.80 (but not all) → ⚠️
   partial-verified** — returned, flagged **"אומת חלקית — N/R פרמטרים אומתו"**,
   naming the unverified parameters.
4. **0 failed and (verified-and-matching ÷ R) < 0.80 → excluded** — reported as
   `insufficient verification`, listing the unverified parameters. **Not** a
   parameter failure — never conflated with a ❌.

The ratio is computed over required (spec) parameters only.

### Outcome categories (used in the verdict/reason)

- **`insufficient verification`** — zero outright failures, but fewer than 80% of
  the required parameters ended verified-and-matching. Excluded from results,
  logged with the unverified parameters. Not a parameter failure.

## Workflow

### Step 1 — Verify the candidate against its JSON params

Look up the candidate in the three JSON files (DATA SOURCE above). For each
required parameter:

1. If the entry's `params` states it → compare to the query using the module's
   direction (`min`/`max`/`contains`) and canonical unit; convert units and
   **show** the conversion + margin (e.g. `P1dB 25 dBm; required ≥ 24 dBm; margin
   +1.0 dB`). Record verified-and-matching or failed.
2. If the entry does **not** state it → **unverified** (never guess a value).

Then assign the verdict with the 80% rule:

- any failed → ❌ rejected (name the parameter and the miss);
- all verified-and-matching → ✅ full match;
- ≥80% verified-and-matching, 0 failed → ⚠️ partial-verified (name the unverified);
- <80% → `insufficient verification` (excluded, name the unverified).

Apply the module's **physics sanity checks** to the stated values (e.g. OIP3
normally above OP1dB); a violation is a red flag — note it in the reason.

### Step 2 — (independent re-verification)

Not run in test mode — there is a single JSON source per parameter and no second
extraction to diff against. Note this plainly in the reason, exactly as the real
skill notes it for the current Gemini-reads mode.

## Output — one component result

Return a single JSON object `{ "components": [ ... ] }`:

- If the candidate **qualifies** (✅ full match, or ⚠️ partial-verified that clears
  the 80% rule) → the list has **exactly one** entry:
  `{ "model", "manufacturer", "url", "verdict" }`. `verdict` is `"match"` (✅) or
  `"partial N/R"` (⚠️ partial-verified).
- If the candidate **does not qualify** (❌ rejected, or `insufficient
  verification`, or not found in the dataset) → the list is **empty** `[]`.

In your chat output, **always state the verdict and the reason** — for a match,
the per-parameter margins; for a reject, the failing parameter and its value, or
the unverified parameters for an `insufficient verification` case. The conductor
logs this text, so it must be present even when the components list is empty.

## Notes

- This skill performs **no** external calls. In `RF_SKILL_MODE=test` the conductor
  also withholds the web/Bash tools, so a datasheet/Gemini/web call is impossible
  even if these instructions were ignored.
- Keep this file behavior-identical to `rf-verify` except this DATA SOURCE change,
  so a diff between the two shows exactly what test mode alters.
