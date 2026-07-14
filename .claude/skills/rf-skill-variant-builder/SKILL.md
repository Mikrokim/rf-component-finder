---
name: rf-skill-variant-builder
description: >-
  Use this to create a NEW skill that is a variant of the base rf-skill
  (folder .claude/skills/rf-skill, frontmatter name "rf-component-search") —
  a skill that behaves and reads exactly like rf-skill EXCEPT for a change the
  user explicitly asks for. Trigger whenever the user says things like "build a
  skill based on rf-skill", "make a variant/version of the skill", "fork the
  skill but change X", "create a version that returns pure results instead of
  Excel", "derive a new skill from the base". The change ("delta") is given as
  free text each run. This skill ALWAYS re-reads the CURRENT rf-skill first (it
  changes over time), preserves everything not named in the delta byte-faithful,
  keeps rf-skill's house writing style, and emits a self-contained new skill
  folder plus a change manifest.
---

# RF-Skill Variant Builder

Produce a **new skill that is a faithful variant of the base `rf-skill`**. The
user hands you one change in plain language ("return pure results, not Excel");
you produce a complete new skill under `.claude/skills/<new-name>/` that is
**identical to the base in every respect except that change** — same workflow,
same guarantees, same verdict system, same triggering behavior, and the **same
writing style** — with its own self-contained copy of the base's `tools/` and
reference files.

The value is a variant you can trust: the user must never wonder whether the
derivation quietly dropped a rule, broke a cross-reference, or drifted in voice.
A variant that changed *more* than asked, and a variant that changed *less* than
asked (left the delta half-applied), are **equally wrong**.

## The governing principle — preserve by default, change by exception

Two inputs define every run:

- **The base** — always the **current** `rf-skill`, read fresh (see Step 1). Never
  a remembered snapshot: the base evolves, and you derive from whatever it is
  today.
- **The delta** — the user's free-text change request, made precise in Step 2.

Your default action for **every** section, tool, reference file, checklist item,
and sentence is **copy it verbatim**. You touch something **only** when the delta
forces it. Every change you make must be justifiable as a direct consequence of
the delta. When in doubt whether something is affected, it is not — leave it
exactly as the base has it.

**"100% compatible" means:** same inputs, same trigger conditions, same steps,
same verdicts and guarantees, same reference-file contract, same house style —
**only** the delta differs, and its ripple (Step 3) is applied coherently.

## Step 1 — Read the CURRENT base, in full, fresh every run

The base changes. **Never derive from memory or from an earlier read.** Before
anything else, read the live base and build a map of it:

1. `.claude/skills/rf-skill/SKILL.md` — the whole thing.
2. **Every reference file it loads** — discover them from the "Required reference
   files" section and any inline load instructions (today: `rf-parameter-rules.md`,
   the per-component modules like `rf-amplifier-module.md`, `rf-excel-template.md`
   — but **list what is actually there now**, do not assume this set).
3. **The `tools/` folder** — every file (today: `run_extract.py`, `extractor.py`,
   `pdf.py`, `config.py`, `rf-llm.env.example`; the real `rf-llm.env` is a
   gitignored secret — see Step 4).

As you read, note the base's **house style** so you can reproduce it: the YAML
frontmatter shape, the "**defined once, referenced throughout**" structure, the
emphatic bold voice, the numbered `Step N` workflow, the Hebrew report language,
the `✅/⚠️/❌` verdict vocabulary, and the audit-checklist format. The variant
must read as if the same author wrote it.

## Step 2 — Turn the free-text delta into a precise, bounded change

The user gives the change in plain language, and it is usually under-specified —
exactly as rf-skill's own Step 1 warns, **ambiguity is the #1 source of wrong
output**. Before generating, ask the user **one** focused round of questions
about anything genuinely ambiguous in the delta, e.g.:

- "Return pure results" → in what exact shape? (JSON object? a chat-only table?
  a specific field set?) Filtered by which parameters?
- Does the change affect **triggering** (the frontmatter `description`/name), or
  only internal behavior?
- Does it **add**, **replace**, or **remove** behavior? (Removing Excel is a
  removal + a replacement of the report step.)
- Does it change the skill's **name** and folder, or just its internals?

Do not ask about things the delta leaves untouched. Restate the finalized change
back to the user as a short, bounded list ("**The delta:** replace the Excel
output in Step 4 with a pure-JSON result keyed by part number; everything else
unchanged") before generating.

## Step 3 — Trace the ripple (the critical step)

The base is **"defined once, referenced throughout"** — a single change almost
never lives in one place. For **each** item in the delta, find **every** location
in the base that mentions or depends on it, and build an **impact map**. Nothing
referenced anywhere may be left dangling.

Search the base for: the section that owns the behavior; every other section that
*references* it; every **reference file** tied to it; every **audit-checklist
item** that enforces it; every **efficiency/notes** mention; and any **tool** that
produces or consumes it.

Worked example — delta = "drop Excel, return pure results" maps to at least:

- **Step 4** ("Report: chat table + Excel") — the owning section.
- **Required reference files** — the load of `rf-excel-template.md`.
- **Core definitions** — "Outcome categories (used in the **coverage sheet**…)".
- **Step 5 audit checklist** — the items about the three sheets, "numbers in chat
  match Excel exactly", the יומן כיסוי column rules.
- **Efficiency notes** and the reference file `rf-excel-template.md` itself.

Applying the delta to Step 4 alone, and leaving those five references pointing at
a workbook that no longer exists, is a **broken** variant. The impact map is what
prevents that.

## Step 4 — Generate the new skill (self-contained)

Create `.claude/skills/<new-name>/` (short lowercase-kebab slug that reflects the
variant, e.g. `rf-skill-pure-results`). Then:

1. **Copy the untouched assets verbatim.** Copy the base's `tools/` and every
   reference file **not** in the impact map into the new folder, byte-for-byte.
   For secrets: copy `rf-llm.env.example` but **do not** copy the real
   `rf-llm.env` (it is gitignored); add the same `.gitignore` the base uses so the
   variant keeps the secret out of git. State in the manifest that the user must
   drop their own `rf-llm.env` into the new `tools/`.
2. **Write the new `SKILL.md`.** Everything **outside** the impact map is copied
   verbatim from the base. Everything **inside** the impact map is rewritten to
   apply the delta **coherently across all impacted spots at once** — the owning
   section and every reference to it change together, or none do. Match the base's
   voice and structure exactly (Step 1 style notes).
3. **New frontmatter.** Give the variant its own `name` and a `description` that
   makes *it* auto-surface — the description must reflect the **changed** behavior
   (e.g. "returns pure JSON results" instead of "chat table + Excel") while
   keeping the trigger phrases for the shared behavior.
4. **Remove what the delta obsoletes.** If the change removes a capability, delete
   the reference files it owned (e.g. `rf-excel-template.md`), remove their load
   instructions, and remove the checklist items that enforced them — do not leave
   orphans.

## Step 5 — Emit a change manifest

Alongside the new skill, give the user a short **"what changed vs. base, and
why"** report — the trust layer:

- Each edited section / reference file / checklist item, tied back to the delta.
- Each **cross-reference** the ripple touched (Step 3) and how it was updated.
- What was **copied verbatim** (tools, untouched reference files, unchanged
  sections) — so the user can see the surface of change is exactly the delta.
- Any manual follow-up (e.g. "add your own `tools/rf-llm.env`").

## Step 6 — Self-verify before handing over

Audit the generated variant; fix anything that fails before reporting:

- [ ] **Only the delta changed.** Diff the new `SKILL.md` against the base; every
      difference is inside the Step 3 impact map. No unrelated section drifted.
- [ ] **The delta is fully applied.** The owning section **and** every reference,
      checklist item, and reference-file load it touches are all updated — no half-
      applied change, no dangling reference to a removed thing.
- [ ] **Self-contained.** `tools/` and all still-needed reference files exist in
      the new folder; the real `rf-llm.env` is excluded and `.gitignore` present.
- [ ] **Tools still wired.** Any invocation paths the base used (`python
      tools/run_extract.py …`) resolve inside the new folder.
- [ ] **Frontmatter correct.** New `name`, new folder, and a `description` that
      surfaces the variant and reflects the changed behavior.
- [ ] **Style matches.** Frontmatter shape, "defined once, referenced throughout"
      structure, emphatic voice, Hebrew report language, verdict vocabulary, and
      checklist format all read like the base.
- [ ] **Manifest present** and honestly lists every change and every verbatim copy.

## Notes

- This skill **reads the base and writes a new skill** (instructions + copied
  assets). It does **not** modify the base `rf-skill`, its tools, or any core
  project code.
- The base is authoritative and **live** — always Step 1 re-reads it. If the base
  and any older understanding disagree, **the current base wins**.
- One delta per run keeps the ripple tractable. For several unrelated changes,
  run once per change (or state them as one bounded list in Step 2 and map each
  through Step 3 independently).
