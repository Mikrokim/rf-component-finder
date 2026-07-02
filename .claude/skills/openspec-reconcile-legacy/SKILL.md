---
name: openspec-reconcile-legacy
description: Review a commit for changes to the legacy specs (specs/rf-component-finder/**) and reconcile them into OpenSpec. For each legacy-spec change, find the OpenSpec capability spec it belongs to, VERIFY the behavior is actually implemented in rf_finder/ code, then — after human approval — apply the edits directly into the openspec/ folder (implemented behavior into openspec/specs/, unimplemented behavior into future-requirements.md / open-questions.md / a new change). Use when a commit edits the legacy specs and you need it reconciled into OpenSpec.
license: MIT
metadata:
  author: rf-component-finder
  version: "1.0"
---

Review a commit that may edit the **legacy** SDD specs under `specs/rf-component-finder/`
and reconcile every such change into **OpenSpec**.

The legacy tree (`specs/rf-component-finder/iteration1/*` + `specs/rf-component-finder/open-questions.md`)
stopped being authoritative after the migration
`2026-06-30-migrate-rf-component-finder-to-openspec`
(`openspec/changes/archive/2026-06-30-migrate-rf-component-finder-to-openspec/`).
`openspec/specs/` is now the source of truth. So a commit that still edits the legacy
files describes intent that may or may not have reached OpenSpec — this skill finds
where it belongs and, critically, **whether the code actually implements it**.

**The repository contract (do not violate):**
- `openspec/specs/<capability>/spec.md` documents **only current, implemented behavior**.
- Future / intended / unimplemented behavior goes to `openspec/future-requirements.md`,
  `openspec/open-questions.md`, or a new `openspec/changes/` proposal — **never** into
  `openspec/specs/`.
- A legacy-spec change is therefore added to `openspec/specs/` **only after** you have
  verified the behavior exists in `rf_finder/` code (and, ideally, is covered by a test).

---

**Input**: An optional commit ref (SHA, tag, `HEAD`, `HEAD~1`, or a range). If none is
given, default to `HEAD`.

---

## Steps

### 1. Resolve the target commit(s)

The argument may be a **single commit** (`HEAD`, `HEAD~1`, a SHA, a tag) **or a range**
(`A..B`). Default to `HEAD`. Normalize it into one diff range `$RANGE` so the rest of the
skill works either way:

```bash
REF="${1:-HEAD}"
if [[ "$REF" == *..* ]]; then
  RANGE="$REF"              # a range (A..B or A...B) — use verbatim
else
  RANGE="${REF}^..${REF}"   # a single commit — diff it against its parent
fi
git log --oneline "$RANGE"  # confirm it resolves and show which commits are covered
```

For a range, the reconciliation works on the **net difference between the endpoints**
(`A..B` = the combined effect of every commit in the range) — a legacy line added in one
commit and reverted in a later one nets to no change, which is what you want. If you also
need per-commit attribution for the report, list them with
`git log --oneline "$RANGE" -- specs/rf-component-finder/`.

### 2. Detect legacy-spec changes

```bash
git diff --name-status "$RANGE" -- specs/rf-component-finder/
```

- **If the output is empty** → the commit does not touch the legacy specs. Report
  *"No changes to `specs/rf-component-finder/` in `<ref>` — nothing to reconcile into
  OpenSpec."* and **STOP**. Do not invent work.
- **If non-empty** → continue. Note added (`A`), modified (`M`), deleted (`D`), and
  renamed (`R`) files.

### 3. Extract the changed behaviors from the diff

```bash
git diff "$RANGE" -- specs/rf-component-finder/
```

Read the actual diff hunks. For each meaningful added/changed line, isolate the
**behavioral claim** (a requirement, scenario, data-model field, or rule). Prefer the
labeled legacy IDs where present (`REQ-1.4`, `REQ-4.2`, `OQ-2`, a `data-models.md`
field, etc.) — they make mapping and traceability exact. Ignore pure prose/formatting
edits that assert no behavior.

Produce a working list of discrete changed behaviors.

### 4. Map each changed behavior to an OpenSpec capability

Use the migration's mapping (from
`.../2026-06-30-migrate-rf-component-finder-to-openspec/{proposal,design,tasks}.md`).
Legacy source → OpenSpec capability spec → code module to check:

| Legacy source | OpenSpec capability (`openspec/specs/<cap>/spec.md`) | Code module(s) to verify against |
|---|---|---|
| `requirements.md` REQ-1 (Structured Form Input) | `structured-form-input` | `rf_finder/form/schema.py`, `rf_finder/form/input.py` |
| `requirements.md` REQ-2.1–2.4 (Parameter Ontology) | `parameter-ontology` | `rf_finder/ontology/parameters.py`, `rf_finder/ontology/components.py` |
| `requirements.md` REQ-2.5 (unit conversion) | `unit-conversion` | `rf_finder/ontology/units.py` |
| `requirements.md` REQ-3 (Mini-Circuits Adapter) | `manufacturer-adapters` | `rf_finder/adapters/base.py`, `rf_finder/adapters/minicircuits.py` |
| `requirements.md` REQ-4 (Result Verification) | `result-verification` | `rf_finder/verifier.py` |
| `requirements.md` REQ-5 (User Output / CLI) | `cli-result-output` | `rf_finder/__main__.py` |
| `data-models.md` (shared models) | `core-data-models` | `rf_finder/models.py` |
| `design.md` / `tasks.md` / `t8-plan.md` | map by the behavior/module it describes, using the rows above | (same as the module it touches) |
| `open-questions.md` | `openspec/open-questions.md` (not a capability spec) | — |

If a changed behavior does not fit any row (e.g. a brand-new component type, a second
manufacturer, config/cache/reporter — all currently stubs or future work), treat it as a
**new capability / future work**, not an update to an existing spec. Before proposing a
new capability, confirm no existing `openspec/specs/` folder already covers the area.

### 5. VERIFY the behavior is actually implemented (mandatory gate)

For each changed behavior, open the mapped code module(s) and confirm the code really
does what the legacy change claims. This gate decides routing — do not skip it and do
not infer implementation from the spec text.

- **Read the module(s)** for the concrete logic (the function/branch/field named by the
  behavior). Grep for the identifiers involved.
- **Run the tests** for that area and record the exact result:
  ```bash
  python -m pytest tests/ -q                 # or the specific test_*.py for the area
  ```
- Classify each behavior as one of:
  - **IMPLEMENTED** — code does it and (ideally) a test covers it.
  - **PARTIAL** — code does some of it; part is missing (e.g. REQ-1.7 validates
    `min ≤ max` but not "sane bounds").
  - **NOT IMPLEMENTED** — no code does it, or the module is a stub
    (`config.py`, `cache.py`, `reporter.py` are stubs), or the code contradicts it.
  - **KNOWN DEFECT** — code attempts it but is broken (e.g. the `between` comparison in
    `verifier.py` raises `NameError`). Document as current behavior + a limitation, not
    as working behavior.

Beware legacy-vs-code disagreements already recorded by the migration (see
`design.md` "Decisions" and `tasks.md` §2, and `openspec/future-requirements.md`):
when the legacy spec and the code disagree, **the implemented code wins** and the spec
must describe what the code actually does.

### 6. Decide where each change lands (routing)

Route strictly by the step-5 verdict:

| Verdict | Where it belongs |
|---|---|
| IMPLEMENTED and **not yet** in the mapped `openspec/specs/<cap>/spec.md` | Add/update a Requirement + `#### Scenario:` in that capability spec (through the OpenSpec change flow — see step 8). |
| IMPLEMENTED and **already** covered in the capability spec | No spec change needed; note it as already-covered (or a wording tweak only). |
| PARTIAL | The implemented part → capability spec; the missing part → `openspec/future-requirements.md` (and/or `open-questions.md`). |
| NOT IMPLEMENTED | `openspec/future-requirements.md` (intended-but-unbuilt) and/or a new `openspec/changes/` proposal to build it. **Never** `openspec/specs/`. |
| KNOWN DEFECT | Capability spec as a "current limitation" scenario **and** an open question / follow-up change to fix it. |
| Pure open-question edit | `openspec/open-questions.md`. |

Cross-check the mapped `openspec/specs/<cap>/spec.md` (and `future-requirements.md` /
`open-questions.md`) to see whether the item is **already** recorded — prefer updating
an existing requirement/entry over adding a duplicate.

### 7. Produce the reconciliation report

Output a table, one row per changed legacy behavior:

| Legacy change (file + ID) | Maps to (capability) | Code verdict (+ test evidence) | Destination | Action |
|---|---|---|---|---|

Then summarize:
- Which items require an `openspec/specs/` update (implemented, not yet documented).
- Which items are future/unimplemented and where they were routed.
- Any legacy-vs-code mismatch found (and that code wins).
- The exact verification commands run and their results.

### 8. Draft the exact edits

This skill applies the reconciled changes itself — it does **not** delegate to the
`openspec-lead` agent. But it never writes to `openspec/` before the human approves.

For every routed change from step 6, draft the **precise edit** you intend to make,
showing the target file and the exact content:

- **IMPLEMENTED, not yet documented** → the new/updated `### Requirement:` block plus at
  least one `#### Scenario:` (WHEN/THEN), written to match the style and heading
  structure already used in the mapped `openspec/specs/<cap>/spec.md`.
- **PARTIAL** → the requirement/scenario for the implemented part (→ capability spec)
  **and** the entry for the missing part (→ `openspec/future-requirements.md`, in that
  file's existing "Not implemented (or only partially implemented)" format).
- **NOT IMPLEMENTED** → the `openspec/future-requirements.md` entry (and/or a new
  `openspec/changes/<name>/` proposal scaffold if the user wants it built).
- **KNOWN DEFECT** → the "current limitation" scenario for the capability spec **and** the
  `openspec/open-questions.md` entry proposing the fix.
- **Pure open-question edit** → the `openspec/open-questions.md` entry.

Read each destination file first and phrase edits as **in-place updates that preserve
unrelated content** — update an existing Requirement/entry rather than appending a
duplicate when the item is already partly recorded.

### 9. Get human approval, then apply the edits to openspec/

- Present the step-7 report and the step-8 drafts, then use the **AskUserQuestion tool**
  to ask the human to approve applying them. Offer, at minimum: *Apply all*, *Apply a
  subset* (let them pick which rows), and *Cancel*. Do not write anything until they
  approve.
- **On approval**, apply the approved edits with the Write/Edit tools:
  - `openspec/specs/<cap>/spec.md` — add/update the Requirement + Scenario(s).
  - `openspec/future-requirements.md` / `openspec/open-questions.md` — add/update entries.
  - a new `openspec/changes/<name>/` proposal — only if the user asked to scaffold one.
- **After writing**, validate the touched specs and report the result:
  ```bash
  OPENSPEC_TELEMETRY=0 openspec validate --strict          # or list --specs
  ```
  If the wrapper fails in Git Bash, use the node fallback in the guardrails below. Fix
  **spec wording only** if validation complains — never edit `rf_finder/` code here.
- Leave staging/committing to the human. **Do not** `git add` / `git commit` the specs or
  changes. Report exactly which files were written.

---

## Guardrails

- **The implementation gate is non-negotiable.** Nothing enters `openspec/specs/` unless
  step 5 confirms the code implements it. When unsure, route to
  `future-requirements.md`, not to `openspec/specs/`.
- **Never write to `openspec/` before the human approves** (step 9). This skill makes the
  edits directly — it does **not** use the `openspec-lead` agent — but the approval gate
  stands: draft first, apply only what the human OKs.
- **Implemented code wins** over legacy spec text on any disagreement; report the
  mismatch.
- **Prefer updating an existing capability spec** over creating a new one; only create a
  new capability when no existing `openspec/specs/` folder fits.
- **Don't fix code here.** If a change reveals a bug or a needed feature, route it to a
  future change/open question — this skill reconciles specs, it does not implement.
- **Stop early** when the commit doesn't touch `specs/rf-component-finder/`.
- If the OpenSpec CLI is needed and its Git Bash wrapper is broken, fall back to
  `OPENSPEC_TELEMETRY=0 node "/c/Users/Admin/AppData/Roaming/npm/node_modules/@fission-ai/openspec/bin/openspec.js" <args>`.
- Note: `openspec/` may be reported as git-ignored (`!! openspec/`) due to the project
  `.gitignore`; if a routed spec edit needs to be tracked, surface that to the maintainer
  rather than working around it.
