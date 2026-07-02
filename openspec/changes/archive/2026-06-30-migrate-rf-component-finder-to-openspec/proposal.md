## Why

The project's specs currently live as free-form SDD documents under `specs/rf-component-finder/iteration1/`. They were written for the first task only, describe *intended* behavior, and have already drifted from the implemented code (e.g. the `between` comparison and the Reporter). We need a single, trustworthy source of truth that reflects **what the system actually does today**, so future work plans against reality rather than aspiration. OpenSpec becomes that source of truth going forward.

## What Changes

- Adopt OpenSpec as the source of truth: capture the **current, implemented** behavior of `rf-component-finder` as initial spec files directly under `openspec/specs/`.
- Translate the legacy `iteration1` specs into OpenSpec requirements + scenarios, but only for behavior that is **actually implemented and verified by code/tests** — planned-but-unbuilt behavior is recorded as gaps, not as current behavior.
- Record every legacy-spec-vs-code disagreement; where they conflict, the **implemented code wins** and the mismatch is reported.
- Capture unresolved/ambiguous items in `openspec/open-questions.md` instead of guessing.
- **Non-behavioral / setup only.** No implementation code changes, no commits, no archiving as part of writing these artifacts. The migration change is archived later with `openspec archive migrate-rf-component-finder-to-openspec --skip-specs`.
- **BREAKING (process, not product):** `specs/rf-component-finder/iteration1/` stops being authoritative; `openspec/specs/` becomes authoritative. The legacy folder is retained read-only for history.

## Capabilities

> Migration note: per the task's migration rules, the initial source-of-truth specs are authored **directly under `openspec/specs/<name>/spec.md`** during apply. This change deliberately does **not** create delta specs under `openspec/changes/migrate-rf-component-finder-to-openspec/specs/`. The list below names the capability specs that the apply step will create.

### New Capabilities
- `parameter-ontology`: Central parameter dictionary (labels, canonical units, accepted units, comparison rules, applicable component types), the component registry, and `params_for` / `component_labels` lookups — as implemented in `rf_finder/ontology/`.
- `unit-conversion`: Pure `to_canonical` conversions for frequency (Hz/kHz/MHz/GHz→GHz), power (W/mW/dBm→dBm), and the dimensionless dB identity — as implemented in `rf_finder/ontology/units.py`.
- `structured-form-input`: Ontology-driven form-schema generation and field collection/validation producing a `QuerySpec` (interactive prompt + testable `answers` seam, empty-field skipping, `min ≤ max`, one-sided `between` ranges) — as implemented in `rf_finder/form/`.
- `manufacturer-adapters`: The `Adapter` interface, the `ADAPTERS` registry + `register` decorator, `AdapterError`, and the Mini-Circuits amplifier adapter (single `httpx` GET, full-table scrape, column→canonical mapping, `MHz` freq tuple, rate-limit delay) — as implemented in `rf_finder/adapters/`.
- `result-verification`: The `verify(spec, candidate)` pipeline: per-parameter normalize + compare, `PASS`/`FAIL`/`UNKNOWN` verdicts, `match`/`partial`/`fail` aggregation, and confidence from `candidate.source` — as implemented in `rf_finder/verifier.py`, **including the documented current limitation that the `between` rule raises `NameError`**.
- `cli-result-output`: The current `python -m rf_finder` flow — interactive component/constraint entry, search-parameter echo, per-adapter error isolation, and the inline grouped match/partial/fail rendering — as implemented in `rf_finder/__main__.py`.

### Modified Capabilities
<!-- None. openspec/specs/ is currently empty; this migration only creates initial specs. -->

## Impact

- **New files (apply step):** `openspec/specs/<capability>/spec.md` (one per capability above), `openspec/open-questions.md`.
- **Tooling/setup:** OpenSpec initialized (`openspec/config.yaml`); `--tools none` was used so no developer-agent/AI-tool instruction files were created or changed.
- **Repository hygiene risk (must resolve during apply):** the project `.gitignore` uses CRLF line endings and an unanchored `config.yaml` rule; git currently reports `openspec/` itself as **ignored** (`!! openspec/`), which would silently prevent the new specs from being tracked. Recorded as an open question.
- **No changes to:** application code under `rf_finder/`, tests under `tests/`, legacy `specs/`, developer-agent instructions, or Claude skills. No commits. No archive.
