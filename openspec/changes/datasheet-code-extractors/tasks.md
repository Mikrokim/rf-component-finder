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

## 4. Held-out fixes (bugs surfaced by new datasheets after the initial land)

- [x] 4.1 TEMPERATURE: add a tier-0 split-label handler — pair `Maximum Operating Temperature N` with `Minimum Operating Temperature M`, reading a single unit-adjacent number per label so a following Storage value cannot leak in (marki silently returned `(85, 125)` instead of `(-54, 85)`). Falls through to tier-1/tier-2 unchanged.
- [x] 4.2 SIZE: add a bill-of-materials / discrete-component distractor (`CAP`/capacitor/`µF`/`nF`/`pF`) so an eval-board capacitor row is not read as the product size; `Ω` is deliberately excluded so a `50Ω` impedance next to a die size is not caught (MAPC-A4029 silently returned a capacitor's `0.98x1.97in` instead of `None`).
- [x] 4.3 Add three source-verified held-out datasheets to the test suite (marki, mapc_a4029, mma016aa) under `evals/pdfs/`, plus plain-text unit scenarios for the split-label and BOM behaviours.
- [x] 4.4 Confirm zero regression: TEMP 8/8 (7 gold + marki) and SIZE 12/12 (7 gold + 5 verified) in the dev harness; full pytest suite green.
