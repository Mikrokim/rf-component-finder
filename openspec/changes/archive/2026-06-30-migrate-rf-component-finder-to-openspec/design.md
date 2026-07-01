## Context

`rf-component-finder` is a local Python CLI that finds RF amplifiers via a structured form, fetches candidates from Mini-Circuits, and verifies them against the request. Its specs live as SDD documents under `specs/rf-component-finder/iteration1/` (`requirements.md`, `design.md`, `data-models.md`, `tasks.md`, `t8-plan.md`) plus a project-wide `specs/rf-component-finder/open-questions.md`. Those documents describe the *intended* iteration-1 system; several parts are stubs or have drifted from the code.

OpenSpec has been initialized at the repo root (`openspec/config.yaml`, schema `spec-driven`) using `--tools none` so no developer-agent/AI-tool instruction files were created or modified. `openspec/specs/` is currently empty. This change plans how to populate it with specs that describe **current implemented behavior**.

**Current implementation status (verified by reading code and probing the verifier):**

| Area | Module | Status |
|------|--------|--------|
| Data models | `models.py` | Implemented (frozen dataclasses, invariant on `value`/`range`) |
| Units | `ontology/units.py` | Implemented (freq→GHz, power→dBm, dB identity) |
| Ontology | `ontology/parameters.py`, `ontology/components.py` | Implemented (6 amplifier params; `amplifier` component) |
| Form | `form/schema.py`, `form/input.py` | Implemented (build_form + collect, interactive + `answers` seam) |
| Verifier | `verifier.py` | Implemented for `contains`/`min`/`max`; **`between` raises `NameError`**; `eq` reachable only for params present in the ontology |
| Adapter base | `adapters/base.py` | Implemented (`Adapter` ABC, `ADAPTERS` **dict** + `register` decorator, `AdapterError`) |
| Mini-Circuits adapter | `adapters/minicircuits.py` | Implemented (single `httpx` GET, scrape `table#maintable`, column map, 1s delay) |
| Config | `config.py` | **Stub (TODO T9)** — not implemented |
| Cache | `cache.py` | **Stub (TODO T10)** — not implemented; adapter not wired to cache |
| Reporter | `reporter.py` | **Stub (TODO T11)** — empty |
| CLI | `__main__.py` | Partial (TODO T12) — interactive only, inline output, no CLI flags, no margin ranking |

## Goals / Non-Goals

**Goals:**
- Produce initial OpenSpec specs under `openspec/specs/` that faithfully describe **currently implemented** behavior, expressed as OpenSpec requirements + `#### Scenario:` blocks.
- Use both the legacy specs and the code as inputs; when they disagree, **document the implemented code** and report the mismatch.
- Record ambiguous/unresolved items in `openspec/open-questions.md` rather than guessing.
- Keep the change reversible and low-risk: artifacts only, no code/commits/archive in this propose step.

**Non-Goals:**
- Changing any implementation code (no bug fixes — including the `between` `NameError`).
- Documenting planned-but-unbuilt behavior (config loader, cache, full Reporter, CLI flags, additional manufacturers/components) as *current* behavior.
- Creating an active OpenSpec change for `iteration1` itself.
- Creating delta specs under `openspec/changes/migrate-rf-component-finder-to-openspec/specs/`.
- Updating developer-agent instructions or creating custom Claude skills.
- Archiving the change (a final, separate step).

## Decisions

**D1 — Author specs directly under `openspec/specs/`, not as change deltas.**
Per the migration rules, the initial source-of-truth specs are created directly at `openspec/specs/<capability>/spec.md`. We deliberately skip OpenSpec's normal delta-spec artifact for this change and use only `proposal.md`, `design.md`, and `tasks.md`. *Rationale:* there is no prior spec to delta against; the migration seeds the baseline. *Consequence:* `openspec status`/`tasks` may report the `specs` artifact as missing/blocked — accepted, and the final archive uses `--skip-specs` so the empty-delta baseline is not synced.
*Alternative considered:* generate full delta specs in the change folder then sync — rejected: produces duplicate specs the rules explicitly forbid.

**D2 — Capability decomposition mirrors the implemented module boundaries.**
Six capability specs: `parameter-ontology`, `unit-conversion`, `structured-form-input`, `manufacturer-adapters`, `result-verification`, `cli-result-output`. *Rationale:* each maps to a cohesive, independently testable module already in `rf_finder/`, keeping requirements traceable to code.
*Alternative:* one monolithic spec — rejected: poor traceability, hard to evolve per-area.

**D3 — Document behavior as-built, including defects, and flag them.**
Where code diverges from the legacy spec, the OpenSpec requirement states the *actual* behavior. Notable: the `between` comparison currently raises `NameError` (variable `canonical` vs `canonical_unit` in `verifier._compare`), so 4 of 6 amplifier parameters (`P1dB`, `Gain`, `NF`, `OIP3`) cannot be verified. We document this as a current limitation/known-defect scenario AND raise an open question on whether to fix it in a follow-up change. *Rationale:* the source of truth must match reality; silently writing the intended behavior would re-introduce the drift we are migrating away from.

**D4 — Exclude stubs from "current behavior" specs.**
`config.py`, `cache.py`, `reporter.py` are TODO stubs; CLI flags and margin-based ranking are unbuilt. These are recorded as gaps/non-goals and open questions, not as requirements. *Rationale:* the rules forbid documenting unimplemented behavior as current.

**D5 — Preserve legacy specs and any existing OpenSpec content; update in place.**
The legacy `specs/` tree is left untouched (read-only history). If `openspec/specs/` or `openspec/open-questions.md` already exist at apply time, update carefully without overwriting unrelated content.

## Risks / Trade-offs

- **`.gitignore` ignores `openspec/`** → `git status` reports `!! openspec/` because the CRLF-terminated `.gitignore` has an unanchored `config.yaml` rule and a stray blank-line pattern that matches arbitrary directories. New specs would be silently untracked. → *Mitigation:* recorded as an open question; the apply step verifies `git check-ignore openspec/specs/...` and, if still ignored, surfaces the fix (e.g. an `!openspec/` un-ignore or normalizing line endings) for the maintainer — without changing application code.
- **Documenting a known defect as current behavior may read as endorsing it** → *Mitigation:* mark such scenarios explicitly as a current limitation and pair each with an open question proposing a follow-up fix change.
- **OpenSpec validation may flag the missing delta `specs` artifact** → *Mitigation:* this is expected for a baseline migration; archive with `--skip-specs`.
- **Legacy-vs-code mismatches could be missed** → *Mitigation:* tasks include an explicit mismatch-reconciliation pass with a recorded mismatch list.

## Migration Plan

1. Confirm OpenSpec root and that `openspec/specs/` is empty (or preserve existing content).
2. For each capability (D2), write `openspec/specs/<capability>/spec.md` from code-confirmed behavior, cross-checked against the legacy specs.
3. Record mismatches and unresolved items in `openspec/open-questions.md` (carry forward relevant legacy OQ-1..OQ-4; add the `between` defect and the `.gitignore` issue).
4. Validate with `openspec validate` / `openspec list --specs`; do not fix code.
5. Leave the change un-archived. The separate, final archive step (run by the maintainer, not part of these artifacts) is:
   `openspec archive migrate-rf-component-finder-to-openspec --skip-specs`

**Rollback:** delete `openspec/specs/` and `openspec/open-questions.md` (and optionally `openspec/`); the legacy `specs/` tree is unchanged, so the project reverts to its prior source of truth with no code impact.

## Open Questions

- Should the `between` `NameError` be fixed in a follow-up OpenSpec change before or after this migration archives? (This migration only documents it.)
- Should `openspec/` be explicitly un-ignored in `.gitignore` (and line endings normalized) as part of adopting OpenSpec, or handled separately by the maintainer?
- Carry-over from legacy `open-questions.md`: OQ-1 (full 10-manufacturer list), OQ-2 (`Candidate.url` robots.txt choice), OQ-3 (warn on row-count drift), OQ-4 (sanity-check valid-but-suspicious input).
