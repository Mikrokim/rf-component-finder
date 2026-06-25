# Implementation Plan (Tasks) — RF Component Finder · Iteration 1

> **Methodology:** Spec-Driven Development (SDD)
> **Sequence:** Requirements → Design → **Tasks** (currently in the Tasks stage)
> **Traces:** [requirements.md](requirements.md) · [design.md](design.md) · [data-models.md](data-models.md)
> **Scope:** Phase 1 (amplifier ontology + structured Form Input) + Phase 2 (Mini-Circuits adapter + Verifier)
> **Status:** Draft pending approval

---

## How to read this plan

- Tasks are ordered so that each builds only on already-completed tasks.
- Each task lists its **Deps** (prerequisite tasks) and the **Reqs** it satisfies.
- `[ ]` = not started · `[~]` = in progress · `[x]` = done.
- Every task that produces core logic includes its tests in the same task
  (test-alongside, per NFR-7) — there is no separate "write tests" phase.
- A task is **done** only when its code is written, its tests pass, and it is
  consistent with the design.

---

## Dependency graph (high level)

```
T1 scaffold
 └─► T2 models ──► T3 units ──► T4 ontology ──► T5 form-input
                                   │                  │
                                   ├──────────────────┴──► T6 verifier
                                   │
                                   └──► T7 adapter-base ──► T8 minicircuits-adapter
                                                                  │
T9 config ─────────────────────────────────────────────────────┐ │
T10 cache ──────────────────────────────────────────────────────┤ │
                                                                 ▼ ▼
                                              T11 reporter ──► T12 CLI wire-up ──► T13 e2e
```

---

## Phase 0 — Project setup

### T1 — Project scaffold
- [ ] Create the `rf_finder/` package layout from [design.md §2](design.md):
      `__main__.py`, `models.py`, `ontology/`, `form/`, `adapters/`,
      `verifier.py`, `reporter.py`, `cache.py`, `config.py`, plus `tests/`.
- [ ] Add `pyproject.toml` with dependencies (D-1): `httpx`, `selectolax`,
      `playwright`, `pdfplumber`, `pyyaml`, `questionary` (form prompts), and dev
      deps (`pytest`). Pin Python ≥ 3.11 (A-3). (`anthropic` deferred to the
      future free-form path.)
- [ ] Add `config.example.yaml` and `.gitignore` (ignore real `config.yaml`).
- **Deps:** none · **Reqs:** NFR-3, NFR-5, A-3, D-1

---

## Phase 1 — Core domain (no network, fully unit-tested)

### T2 — Data models
- [ ] Implement all frozen dataclasses in `models.py` exactly per
      [data-models.md](data-models.md): `ParamConstraint`, `QuerySpec`,
      `RawValue`, `Candidate`, `ParamVerdict`, `VerifiedCandidate`.
- [ ] Define the string-enum constants (comparison / status / overall / source).
- [ ] Tests: construction + invariant checks (e.g. exactly one of `value`/`range`).
- **Deps:** T1 · **Reqs:** REQ-1.1, REQ-3.5, REQ-4.1–4.5

### T3 — Units conversion
- [ ] Implement `ontology/units.py`: `to_canonical(value, from_unit, canonical)`
      for frequency (Hz/kHz/MHz/GHz→GHz), power (W/mW/dBm→dBm), and
      dimensionless ratios (dB→dB, identity; used by Gain/NF).
- [ ] Tests: a conversion table incl. `6000 MHz → 6.0 GHz` and a dBm/mW round-trip.
- **Deps:** T1 · **Reqs:** REQ-2.5

### T4 — Ontology (parameters + components)
- [ ] Implement `ontology/parameters.py` with the `PARAMETERS` dict for amplifier
      params (`freq_range`, `P1dB`, `Gain`, `NF`, `OIP3`, `Pout`) incl. display
      `label`, canonical unit, accepted `units`, comparison rules — per
      [design.md §4.1](design.md).
- [ ] Implement `ontology/components.py` with the `amplifier` component (+ label).
- [ ] Add helper lookups: `params_for(component_type)` (filter on `applies_to`),
      `component_labels()`.
- [ ] Tests: `params_for("amplifier")` returns the 6 expected params; unknown
      component → empty/`None`.
- **Deps:** T2, T3 · **Reqs:** REQ-2.1–2.4, REQ-1.2, REQ-1.3

### T5 — Form input (structured, ontology-driven)
- [ ] Implement `form/schema.py` (`build_form(component_type) -> FormSchema`) and
      `form/input.py` (`collect(schema) -> QuerySpec`) per [design.md §5](design.md).
- [ ] Generate fields from the ontology (range vs scalar by `comparison`), offer
      canonical-first unit options, skip empty fields, validate (numeric,
      `min ≤ max`, sane bounds), store chosen unit on each constraint.
- [ ] Isolate the interactive prompt lib behind a seam so field→constraint logic
      is testable without a TTY. Provide equivalent CLI-flag entry for scripting.
- [ ] Tests (the iteration's keystone): filled fields (amplifier; freq 2–6 GHz;
      P1dB 26 dBm; rest empty) → the exact `QuerySpec` in [design.md §5.2](design.md);
      plus a validation-error case (`min > max`) and an all-empty case.
- **Deps:** T4 · **Reqs:** REQ-1.1–1.7

### T6 — Verifier
- [ ] Implement `verifier.py`: `verify(spec, candidate) -> VerifiedCandidate`
      with `compare` (min/max/contains/eq) and `decide` (match/partial/fail)
      per [design.md §7](design.md). Uses `units.to_canonical`.
- [ ] Tests: full matrix — PASS/FAIL for each comparison, `contains` with the
      `(2,6) GHz ⊆ candidate band` case, `UNKNOWN`→`partial`, any-FAIL→`fail`.
- **Deps:** T4, T2 · **Reqs:** REQ-4.1–4.5, REQ-2.4

---

## Phase 2 — Retrieval & integration

### T7 — Adapter base + registry
- [ ] Implement `adapters/base.py`: `Adapter` ABC (`manufacturer`,
      `supported_components`, `search()`), the `ADAPTERS` registry, and
      `AdapterError(manufacturer, context, cause)` — per [design.md §6.1](design.md).
- [ ] Tests: registry self-registration; `AdapterError` carries context.
- **Deps:** T2 · **Reqs:** REQ-3.1, REQ-3.6, NFR-4

### T8 — Mini-Circuits adapter
- [ ] **I-1:** Inspect the live request mechanism of
      `WebStore/Amplifiers.html` (GET query string vs AJAX/POST) and decide
      `httpx` vs `playwright`. Record the finding in the adapter docstring.
- [ ] **I-2:** Capture an HTML fixture of the amplifier results table into
      `tests/fixtures/minicircuits_amplifiers.html`.
- [ ] Implement `adapters/minicircuits.py`: build the search (push only the
      frequency band to the site filter), scrape the results table, and map
      columns→canonical using the confirmed table in [design.md §6.2](design.md).
      Combine `F Low`/`F High` (MHz) into one `RawValue((low,high),"MHz")`.
      Respect robots.txt + rate limiting.
- [ ] Tests: parse the saved fixture → expected `Candidate` list with correct
      canonical `raw_params` (offline, no network).
- **Deps:** T7, T4 · **Reqs:** REQ-3.2–3.6, NFR-6

---

## Phase 3 — Infrastructure & wiring

### T9 — Config loader
- [ ] Implement `config.py`: load `config.yaml` (site list, rate limits, cache
      TTL); validate; clear error if missing. No secrets in code. (Reserve an
      optional Anthropic-key entry for the future free-form path.)
- [ ] Tests: load `config.example.yaml`; missing-file error path.
- **Deps:** T1 · **Reqs:** NFR-5

### T10 — Cache
- [ ] Implement `cache.py`: SQLite get/set keyed per
      [design.md §9.1](design.md), with TTL from config.
- [ ] Wire the Mini-Circuits adapter's HTTP fetch through the cache.
- [ ] Tests: set/get round-trip; TTL expiry (injected clock, no real sleep).
- **Deps:** T9, T8 · **Reqs:** NFR-1, NFR-2

### T11 — Reporter
- [ ] Implement `reporter.py`: print the entered `QuerySpec` summary first; rank
      match>partial>fail, and within a tier by margin of the strongest constraint
      (per [design.md §8](design.md)); render per-candidate table (per-param
      PASS/FAIL/UNKNOWN, confidence badge, link); explicit "no results" message.
- [ ] Tests: cross-tier ordering; within-tier margin tiebreak; no-results
      message; QuerySpec summary echo.
- **Deps:** T6 · **Reqs:** REQ-5.1–5.4

### T12 — CLI wire-up
- [ ] Implement `__main__.py`: run the form (or parse CLI flags) → `QuerySpec` →
      dispatch to registered adapters (per-adapter error isolation, NFR-4) →
      Verifier → Reporter.
- [ ] Manual run: `python -m rf_finder` (interactive form), and the flag form
      `python -m rf_finder --type amplifier --freq-min 2 --freq-max 6 --freq-unit GHz --p1db 26`.
- **Deps:** T5, T8, T11, T10 · **Reqs:** REQ-1.1, REQ-5, NFR-4

---

## Phase 4 — Validation

### T13 — End-to-end acceptance
- [ ] Run the live target search via the form (amplifier; freq 2–6 GHz; P1dB
      26 dBm) and confirm all 5 Definition-of-Done criteria in
      [requirements.md §7](requirements.md): valid QuerySpec summary shown, real
      Mini-Circuits candidates returned, each marked match/partial/fail with
      `table` confidence, unit tests green.
- [ ] Mark a live integration test (network) as optional/skippable in CI.
- **Deps:** T12 · **Reqs:** Definition of Done (§7)

---

## Traceability summary

| Requirement group | Tasks |
|-------------------|-------|
| REQ-1 (Form Input) | T4, T5 |
| REQ-2 (Ontology/Units) | T3, T4 |
| REQ-3 (Adapter) | T7, T8 |
| REQ-4 (Verifier) | T2, T6 |
| REQ-5 (Output) | T11, T12 |
| NFR-1/2 (cost/perf) | T10 |
| NFR-3 (extensibility) | T1, T7 |
| NFR-4 (robustness) | T7, T12 |
| NFR-5 (config) | T9 |
| NFR-6 (compliance) | T8 |
| NFR-7 (testability) | T2–T6, T8 (tests in-task) |

---

## Suggested build order (critical path)

`T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T11 → T12 → T13`
(T9, T10 can be done any time after T1/T8 respectively; they are not on the
parser/verifier critical path.)
