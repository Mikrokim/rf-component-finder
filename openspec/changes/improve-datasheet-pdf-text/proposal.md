## Why

The text this module hands to the LLM is the largest source of extraction errors, and measurement shows the module's own PDF-to-text step is causing them — not the model, and not the prompt.

`datasheet_text_from_pdf` returns `page.extract_text()`, which flattens a page into a line stream ordered by y-then-x. A specification table's geometry is destroyed: the Min/Typ/Max column a number sits under becomes unrecoverable, so the extractor guesses. Measured on `CMPA1E1F060D` with `llama3.1:8b` at `temperature=0`, changing **nothing but the text**, Drain Voltage went from `{"min": 28, "max": 28}` (wrong — that table's Min and Max columns are empty) to `{"typ": 28}` (correct).

Two further measurements shape this change:

- **Whole-document text actively harms extraction, even when it fits.** At `num_ctx=8192` the full document occupied 5,370 of 8,192 tokens with no truncation, and the model returned `length`/`width` as `null` and Voltage as `{"min": 28, "value": [28]}`. The same model, same prompt, given only the one relevant page returned `typ=4530` and `typ=28` correctly — in ~20s instead of 323s. This is context dilution, not truncation, so a larger window is not the remedy. The module must be able to hand out *focused, window-sized* text rather than one undifferentiated blob.
- **Page furniture is 4–45% of a datasheet, and it carries real specs.** Across five vendors (MACOM, Analog Devices, Guerrilla RF, Hittite, AMCOM) the repeated banner/footer costs 4% (ADCA3270) to 45% (CMPA1E1F060D). It cannot simply be deleted: the banner states the frequency range in **4 of the 5** (`75Ω 45 to 1218 MHz`, `13.75 - 15.5 GHz`, `8 to 12 GHz Useable`, `8 - 14 GHz`), plus power ratings (`60 W`, `2 Watt`). Emitting it **once** removes the repetition and keeps the data.

## What Changes

- **Layout-preserving page text.** Extract with `layout=True` so table columns stay spatially aligned and a number's position still identifies its column. This is the change that fixed field placement in measurement.
- **De-duplicated page furniture, guarded.** A line repeating on ~every page is furniture: keep its **first** occurrence, drop the repeats. A narrow table-header guard (`min|max|typ|nominal|parameter|units|symbol|conditions|rating|value`) is never de-duplicated, so a spec-table header can never be collapsed and cost us the column context `layout=True` exists to preserve. Verified against all five datasheets: the guard matches **none** of the real furniture (so it costs no savings) and **all** of the real table headers (so it protects every one).
- **Window-sized segmentation.** The module gains the ability to yield the datasheet as *segments* sized to a caller-supplied budget, ordered by relevance to the requested parameter names, using deterministic model-free scoring. This deliberately serves **both** consumption strategies without committing to either: a caller may take the single best-matching segment, or iterate every segment and merge. Choosing between those — and any multi-call orchestration — is **out of scope** and stays with `extractor.py`.
- **No breaking change.** `datasheet_text_from_pdf(path, pages=None)` keeps its signature and its explicit-`pages` behavior. Segmentation is a new, separate entry point; existing callers and tests are unaffected.
- **Honest degradation.** A PDF with no ruled tables, or an image-only page, must degrade to today's behavior rather than return less text than before.

## Capabilities

### New Capabilities
<!-- None. PDF-to-text already belongs to the datasheet-extraction capability. -->

### Modified Capabilities
- `datasheet-extraction`: the **Extract datasheet text from a PDF** requirement changes. It currently specifies plain `extract_text()` joined by blank lines. It gains layout preservation, guarded furniture de-duplication, and a new segmentation entry point that yields relevance-ordered, budget-sized text. The LLM extraction-contract and `RawValue`-mapping requirements in the same capability are untouched.

## Impact

- **Code:** `rf_finder/datasheet/pdf.py` only. `extractor.py`, `mapping.py`, and `config.py` are untouched.
- **Tests:** `tests/test_datasheet_pdf.py`. `_join_page_text`'s dependency-free, fake-page testability must be preserved — the new de-duplication, guard, and segmentation logic have to be unit-testable the same way, without a real PDF.
- **Dependencies:** none added. `layout=True` is an existing `pdfplumber` feature; de-duplication and scoring are plain Python. (`pymupdf4llm` was evaluated and rejected: it is AGPL-3.0, and the free path already recovers the measured benefit.)
- **Ordering:** this modifies a requirement introduced by the in-flight `add-datasheet-extraction` change, which should land first; its `datasheet-extraction` spec is this delta's baseline.
- **Callers:** none in the product — the module is not yet wired into any adapter or the search pipeline, so there is no downstream behavior to regress. `evals/eval_datasheet.py` and `evals/eval_gold.py` exercise this path and will measure the change.
- **Known limits, deliberately not addressed:**
  - **Cost is not uniform.** De-duplication saves 45% on one vendor and 4% on another. Cleanup is an optimization; focused context is the actual fix.
  - **Performance-curve pages cannot be detected reliably.** Structurally a plot is indistinguishable from a mechanical drawing (measured: the plot page is 50% image area, the Mechanical page carrying `Die size: 4530 µm x 6090 µm` is 47%), so any area-based rule would delete the dimensions. Heading keywords reach only 3 of 5 vendors. Left out rather than done wrong; a repeated-axis-label signal was observed on two vendors and is recorded as future work.
  - **Evaluation-board / BOM sections are a known hallucination trap** — parts lists carry their own `50V`, `100V`, `0.1uF`, `0 Ohm` values, and eval-board markers appear in **5 of 5** vendors. Suppressing them is attractive but unproven, and a naive keyword could drop a Features page that merely mentions an evaluation board. Deferred until it can be verified.
- **Out of scope:** the wording of `EXTRACT_RF_PARAMETERS_INSTRUCTION`, the provider/model choice in `rf_finder.config`, Ollama's `num_ctx`, multi-call orchestration and result merging, and the `evals/` tooling itself.
