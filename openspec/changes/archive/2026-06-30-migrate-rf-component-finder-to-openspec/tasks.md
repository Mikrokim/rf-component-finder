## 1. Preparation & inputs

- [x] 1.1 Confirm git status/branch and that this work touches only `openspec/` (no `rf_finder/`, `tests/`, or `specs/` edits; no commits).
- [x] 1.2 Confirm OpenSpec root is initialized (`openspec/config.yaml`, schema `spec-driven`) and that no developer-agent/AI-tool instruction files were created or changed.
- [x] 1.3 Review legacy specs under `specs/rf-component-finder/iteration1/` (`requirements.md`, `design.md`, `data-models.md`, `tasks.md`, `t8-plan.md`) and `specs/rf-component-finder/open-questions.md`.
- [x] 1.4 Inspect the related current implementation in `rf_finder/` (models, ontology, units, form, verifier, adapters, reporter, config, cache, `__main__`) and `tests/`; treat implemented behavior as current system behavior.
- [x] 1.5 Check whether `openspec/specs/` and `openspec/open-questions.md` already exist; if so, plan to update them in place and preserve unrelated content.

## 2. Reconcile legacy specs vs. implemented code

- [x] 2.1 For each capability, diff legacy intent against actual code; where they disagree, choose the **implemented code** as truth and note the mismatch.
- [x] 2.2 Record the confirmed mismatches, at minimum:
  - Verifier `between` rule raises `NameError` (`canonical` vs `canonical_unit` in `verifier._compare`) → `P1dB`/`Gain`/`NF`/`OIP3` cannot be verified today.
  - Reporter (`reporter.py`) is an empty stub; result rendering is done inline in `__main__.py` (no margin-based ranking, no confidence badge column).
  - Config loader (`config.py`) and SQLite cache (`cache.py`) are stubs; adapter is not wired to a cache; rate-limit delay is hard-coded (1.0s).
  - CLI exposes interactive prompts only; the `--type/--freq-min/...` flags described in legacy design are not implemented.
  - Component type is entered as free text in `__main__` (validated against `COMPONENTS`), not chosen from a selection list as legacy REQ-1.3 implies.
  - Adapter registry is a `dict` keyed by manufacturer with a `register` decorator (legacy design showed a `list`); `supported_components` is a `set` on the concrete adapter though the ABC annotates `list[str]`.
  - Mini-Circuits adapter does no server-side frequency filtering (already noted in `t8-plan.md`); it scrapes all rows and the Verifier filters.
- [x] 2.3 Keep the mismatch list available to feed §3 specs and §4 open-questions; do not change any code to resolve mismatches.

## 3. Create initial source-of-truth specs under `openspec/specs/`

> Author these directly under `openspec/specs/<capability>/spec.md`. Do NOT create delta specs under `openspec/changes/migrate-rf-component-finder-to-openspec/specs/`. Describe only currently implemented behavior, using OpenSpec requirements with at least one `#### Scenario:` each.

- [x] 3.1 `openspec/specs/parameter-ontology/spec.md` — `PARAMETERS` (label, canonical_unit, accepted units, comparison rule, applies_to) for the 6 amplifier params; `COMPONENTS` (`amplifier`); `params_for` filtering and `component_labels`.
- [x] 3.2 `openspec/specs/unit-conversion/spec.md` — `to_canonical` for frequency (Hz/kHz/MHz/GHz→GHz), power (W/mW/dBm→dBm, `dBm = 10·log10(mW)`), dB identity; error cases (unknown unit, non-positive power, unsupported canonical).
- [x] 3.3 `openspec/specs/structured-form-input/spec.md` — `build_form` field generation (range vs scalar ordering by comparison) and `collect`: ontology-driven fields, empty-field skipping, `min ≤ max` validation, one-sided `between` defaults (−∞/+∞), `contains` requiring both bounds, chosen-unit stored unconverted, the `answers` test seam.
- [x] 3.4 `openspec/specs/manufacturer-adapters/spec.md` — `Adapter` interface, `ADAPTERS` registry + `register` decorator, `AdapterError`, and the Mini-Circuits adapter behavior (single `httpx` GET to `Amplifiers.html`, `table#maintable` scrape, header normalization + `COLUMN_MAP`, `F Low`/`F High` combined into one MHz `RawValue` tuple, `"DC"`→0.0, missing sentinels dropped, `source="table"`, ≥1s inter-request delay, raises `AdapterError` on HTTP error / missing table).
- [x] 3.5 `openspec/specs/result-verification/spec.md` — `verify`: per-constraint normalize + compare; `contains`/`min`/`max` PASS/FAIL rules; `UNKNOWN` when param absent; aggregation any-FAIL→`fail`, else any-UNKNOWN→`partial`, else `match`; confidence from `candidate.source` (table/datasheet/unknown). Include an explicit **current-limitation** scenario: `between` raises `NameError` and `eq` is reachable only for ontology params.
- [x] 3.6 `openspec/specs/cli-result-output/spec.md` — `python -m rf_finder` flow: component prompt (default `amplifier`), constraint entry, search-parameter echo (including `any` / `≥` / `≤` rendering for open `between` ranges), per-adapter error isolation, grouped MATCH/PARTIAL/FAIL output with per-param ✓/✗/? markers, "no matching..." message, and the optional show-fails prompt.
- [x] 3.7 Cross-check every authored requirement against code one more time; remove anything not actually implemented.

## 4. Record open questions and mismatches

- [x] 4.1 Create/update `openspec/open-questions.md` carrying forward relevant legacy questions: OQ-1 (full 10-manufacturer list), OQ-2 (`Candidate.url` robots.txt choice), OQ-3 (warn on row-count drift), OQ-4 (sanity-check valid-but-suspicious input).
- [x] 4.2 Add migration-specific open questions: whether/when to fix the `between` `NameError` in a follow-up change; whether to un-ignore `openspec/` and normalize `.gitignore` line endings (git currently reports `!! openspec/`).
- [x] 4.3 Record the §2 mismatch findings (legacy spec vs. implemented behavior) where they belong (open-questions and/or as current-limitation notes in the relevant spec).

## 5. Validate the migration (no code changes, no commit, no archive)

- [x] 5.1 Run `openspec list --specs` and `openspec validate` to confirm the new specs are well-formed; fix spec wording only (never application code).
- [x] 5.2 Verify `git check-ignore openspec/specs/...`; if specs are ignored, surface the `.gitignore` fix to the maintainer (do not change application code) per OQ in §4.2.
- [x] 5.3 Confirm no edits were made to `rf_finder/`, `tests/`, `specs/`, developer-agent instructions, or Claude skills, and that no commit was created.

## 6. Archive (final, separate step)

- [ ] 6.1 After the specs are reviewed and accepted, archive the migration change with:
  `openspec archive migrate-rf-component-finder-to-openspec --skip-specs`
