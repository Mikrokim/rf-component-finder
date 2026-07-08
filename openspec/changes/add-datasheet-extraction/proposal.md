## Why

The datasheet-fallback layer (`future-requirements.md` REQ-2.2) — enriching parameters that manufacturer listing pages don't publish (Size, MSL, Temperature, ...) by reading the part's datasheet PDF with `source="datasheet"` — was **built and tested ahead of having an OpenSpec spec**. The code already exists in `rf_finder/datasheet/` and is fully covered by `tests/test_datasheet_{pdf,extractor,mapping}.py`, but it has no source-of-truth requirements. This change retroactively captures the already-implemented, already-verified module so `openspec/specs/` reflects reality.

This is a **documentation/capture** change: no feature code is written or modified. Every requirement and scenario below is grounded in existing code and mirrors an existing passing test.

## What Changes

- Introduce the `datasheet-extraction` capability spec documenting the three implemented primitives of `rf_finder/datasheet/`:
  - **PDF → text** (`pdf.py`): `datasheet_text_from_pdf` / `_join_page_text` — open a datasheet PDF with `pdfplumber` and return its joined page text.
  - **LLM extraction contract** (`extractor.py`): the published `EXTRACT_RF_PARAMETERS_INSTRUCTION` and `extract_rf_parameters`, which run a config-selected LLM and return a normalized `{unit, min, typ, max, value, condition}` object (or `None`) per requested parameter, enforcing the contract on the model's reply.
  - **Extractor-output → Verifier mapping** (`mapping.py`): `to_raw_params`, which converts extractor output into `{canonical_name: RawValue}` shaped by each parameter's ontology `comparison` rule, with unit reconciliation and skipping of unmappable specs.
- **NOT breaking.** No code changes; no behavior changes. The `source="datasheet"` / `confidence="datasheet"` enum slots already exist in `core-data-models` and `result-verification` and are unchanged, so those capabilities are **not** modified by this change.

## Capabilities

### New Capabilities
- `datasheet-extraction`: The standalone, tested datasheet parameter-extraction module — PDF-to-text extraction, the LLM extraction contract and its output normalization/error handling, and the extractor-output-to-`RawValue` mapping keyed by ontology comparison rules.

### Modified Capabilities
<!-- None. The datasheet source/confidence enum slots in core-data-models and result-verification already exist and are unchanged. -->

## Impact

- **New spec file at archive time:** `openspec/specs/datasheet-extraction/spec.md` (created when this change is archived/synced).
- **Dependency:** the module requires the optional `llm` extra (`pip install rf-finder[llm]`, i.e. `genaifabric`) — but only when extraction actually *runs*. Importing the module and running the scraping/verification path stay free of that dependency. PDF-to-text uses `pdfplumber`, already a project dependency.
- **Config:** the model/provider are module-level constants in `rf_finder/config.py` (`DATASHEET_PROVIDER = "local"`, `DATASHEET_MODEL = "qwen3:8b"`); there is no config-file loader yet.
- **Out of scope — integration remains future work.** This capability documents the module's contract ONLY. The module is **not yet wired into any adapter or the search/CLI flow** — no adapter calls it. Wiring datasheet extraction into the search pipeline (the enrichment that makes REQ-2.2 end-to-end) is explicitly NOT part of this capability and remains a future item. At archive time, `future-requirements.md` REQ-2.2 and the iteration-2 datasheet note should be updated from "Not implemented" to "module implemented (see `datasheet-extraction`), integration pending".
