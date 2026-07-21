## 1. Code extractor module

- [x] 1.1 Create `rf_finder/datasheet/code_extractors.py` with the public API `temp_range(text)`, `size_dims(text)`, `msl_level(text)`.
- [x] 1.2 Port the validated TEMPERATURE logic from scratchpad `temp_v2.py` verbatim: operating/operation + case/junction/ambient + `Temp.` anchor, tier-2 bare `Temperature Range` fallback gated by non-storage left context, `U+F0B0`→`°` normalization, signed-or-unit-adjacent number acceptance, en/em dash as minus.
- [x] 1.3 Port the validated SIZE logic from scratchpad `size_v2.py` verbatim: `A×B` requiring a length unit or size keyword, distractor rejection (thru-hole/diameter/tolerance/bond pad/MTTF/hours/×10), zero-dimension rejection, curly-quote inch support.
- [x] 1.4 Port the validated MSL logic (anchor + first standalone 1–6 digit) from scratchpad `extractors.py`.
- [x] 1.5 Export the three functions from `rf_finder/datasheet/__init__.py`.

## 2. Tests

- [x] 2.1 Add `tests/test_datasheet_extractors.py` parametrized over 4 source-verified datasheets (grf2111, adca3270, am06013033wm, RWLA1001) asserting TEMP, SIZE, MSL.
- [x] 2.2 Add unit scenarios from the spec that do not need a PDF (storage-exclusion, footnote superscript, en-dash minus, MTTF distractor, "24 Pad" size, reflow-vs-MSL) as plain-text assertions.
- [x] 2.3 Confirm the datasheet PDFs used by the tests are available under `evals/pdfs/` (move `RWLA1001.pdf` into the repo if the test must not depend on `Downloads`).

## 3. Verify

- [x] 3.1 Run `python -m pytest tests/test_datasheet_extractors.py -v` and confirm all pass.
- [x] 3.2 Run the full existing suite to confirm no regression.
- [x] 3.3 Run `openspec validate datasheet-code-extractors` and resolve any issues.
