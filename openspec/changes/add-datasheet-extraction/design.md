## Context

The datasheet parameter-extraction module already exists in `rf_finder/datasheet/` and is fully covered by tests. It was written to satisfy the datasheet-fallback intent (`future-requirements.md` REQ-2.2): manufacturer listing pages often omit Size, MSL, and Temperature, which live only in per-part datasheet PDFs. The module harvests those (and any other requested parameter) from a datasheet with `source="datasheet"`.

This design records the technical shape of the **already-implemented** module so the retroactive spec is anchored to real decisions. It is primarily a capture; the only code change is one deliberate hardening of the missing-unit policy in `mapping.py` (see Decisions). The module has three primitives that form a pipeline but are individually testable:

1. `pdf.py` — `_text_from_stream` / `_join_page_text`: PDF → raw text (via `pdfplumber`); the by-URL fetch (`datasheet_text_from_url`) is specified in `add-datasheet-orchestration-pipeline`.
2. `extractor.py` — `EXTRACT_RF_PARAMETERS_INSTRUCTION` + `extract_rf_parameters`: raw text + requested names → normalized `{unit, min, typ, max, value, condition}` per name (via a config-selected LLM through `genaifabric`).
3. `mapping.py` — `to_raw_params`: extractor output → `{canonical_name: RawValue}` for the Verifier.

## Goals / Non-Goals

**Goals:**
- Document the module's contract as source-of-truth requirements, each grounded in a passing test.
- Capture the deliberate design choices (guaranteed-value selection by comparison direction, unit reconciliation, optional-dependency isolation, contract enforcement on model output) so they are not lost or accidentally "fixed".

**Non-Goals (explicitly out of scope):**
- **Integration into the search pipeline.** The module is a standalone layer; no adapter or the CLI/search flow calls it today. Wiring datasheet extraction into adapters (fetch the datasheet PDF, run extraction, merge `source="datasheet"` candidates into results) is NOT part of this capability and remains future work under `future-requirements.md` REQ-2.2.
- Any change to the `source`/`confidence` enums — the `"datasheet"` slots already exist in `core-data-models` / `result-verification` and are unchanged.
- A config-file loader for the model/provider (they remain module-level constants in `rf_finder/config.py`).
- Fetching/caching datasheet PDFs, choosing which PDF belongs to a part, or deciding which parameters to request — all deferred to the future integration change.

## Decisions

- **Three separable primitives, not one monolith.** PDF-to-text, LLM extraction, and RawValue mapping are independent functions with pure, testable seams (fake page objects for `_join_page_text`; an injectable `runtime` mock for `extract_rf_parameters`; the real Verifier for `to_raw_params`). *Why:* each layer is verifiable without a real PDF, network, or API key.
- **Optional `llm` dependency is import-safe.** `genaifabric` is imported lazily inside `_get_runtime`, so importing `rf_finder.datasheet` (and running the scraping/verification path) never requires the `llm` extra or an API key. *Alternative rejected:* a top-level import would force every user of the package to install `genaifabric`.
- **Model AND provider from config constants, not call arguments.** `extract_rf_parameters` reads both `DATASHEET_MODEL` and `DATASHEET_PROVIDER` from `rf_finder.config`; neither is a call parameter. Only `runtime` is injectable (chiefly for tests, to supply a MockProvider-backed GenAIFabric). *Why:* one place to change the model/provider; callers stay simple and can't drift from config. *Trade-off:* no per-call model/provider selection and no config file yet.
- **Enforce the contract on the model's reply, don't trust it.** The output is reshaped to exactly the requested keys — missing keys → `None`, found keys normalized to all six fields, invented keys dropped — plus reply cleanup for thinking preambles / markdown fences. *Why:* local thinking models (qwen3) are chatty and inconsistent; the caller gets a uniform shape regardless.
- **Map to the GUARANTEED value by comparison direction.** For a `min` ("at least") rule the mapping uses the stated `min` (then `typ`) and never borrows `max`; for a `max` ("at most") rule it uses `max` (then `typ`) and never borrows `min`. A spec with only the opposite end is dropped → Verifier UNKNOWN. *Why:* borrowing the opposite end would be optimistic and could yield a wrongful PASS. *Alternative rejected:* always use `typ`/any-available — unsafe for a guarantee.
- **Shape by ontology `comparison`, unit by ontology `canonical_unit`.** `to_raw_params` derives the RawValue shape (`contains` → tuple/list; `min`/`max`/`eq` → scalar) and reconciles stated unit spellings (`C`→`degC`, `Ohms`→`Ohm`) from the ontology, then proves compatibility by driving the real `verify()`. *Why:* the mapping must match what the Verifier expects, not merely look plausible.
- **Missing unit → fill canonical ONLY when unambiguous (the one behavior change).** When a `value` has no unit, `to_raw_params` fills the parameter's canonical unit only if the parameter has a single accepted unit (`len(units) == 1`) — dimensionless (MSL) or single-unit (Gain). For a multi-unit parameter (`freq_range` GHz/MHz, `P1dB`/`Psat` dBm/W/mW) it omits the parameter (→ UNKNOWN) instead of assuming the canonical unit. *Why:* guessing GHz for a unit-less frequency could be a 1000× error and a wrongful PASS; leaving it UNKNOWN is honest and consistent with the min/max "never borrow an optimistic value" rule. *Alternative rejected:* the previous blanket `empty→canonical` fallback, which silently guessed for multi-unit parameters. *Generic, not per-parameter:* the rule reads `len(units)` from the ontology rather than a hand-maintained per-parameter flag, so it stays correct automatically if a parameter's accepted-unit list changes.

## Risks / Trade-offs

- **[Local LLM output is nondeterministic]** → the contract is enforced structurally (key set, field normalization, reply cleanup) and every enforcement path has a unit test with a mock runtime; real-model quality is out of scope for this spec.
- **[Module is documented but unused]** → the spec is honest that integration is future work; the risk is that readers assume the search flow already uses datasheets. Mitigated by the explicit Non-Goals here and the Impact/Out-of-scope note in the proposal.
- **[`max`-rule dimension parsing picks the largest number]** → correct for a bounding-box "worst case" (Size), but any future `max` parameter whose string is not a set of comparable dimensions could be mis-parsed. Acceptable given current parameters; revisit if new `max` string parameters are added.

## Open Questions

- **How does extraction get wired into search?** Which component fetches the datasheet PDF for a given part, which parameters it requests, and how `source="datasheet"` candidates merge with listing-page candidates — all deferred to the future REQ-2.2 integration change. Not resolved here.
- **Config-file loader for model/provider?** Currently module-level constants; a loader (`NFR-5`) is a separate future change.
