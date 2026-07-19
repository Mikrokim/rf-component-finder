## Why

The `datasheet-extraction` path returns the wrong result — or a fabricated one — for three of the four parameters this project most needs (MSL, VDD, physical size; operating/storage temperature already extracts correctly). Measured on `llama3.1:8b` at `temperature=0`, these are **not** text-rendering failures (the companion change `improve-datasheet-pdf-text` owns the text) but extraction-logic failures, with three distinct causes:

- **VDD is not recognised under vendor wording.** A request for `VDD` on `CMPA1E1F060D` — which states `Drain Voltage 28 V` — returns `{}`; the model does not map the requested name to the datasheet's term. Adding a single synonym line to the instruction returned `{"typ": 28}`.
- **Absent categorical parameters are fabricated.** `MSL` extracts correctly where stated (`3` on ADCA3270, `1` on GRF2111) but on a datasheet without it (CMPA) the model emits the instruction's own example (`"3"`). Abstracting that example AND adding an explicit "absent → null" rule both failed — the model then parroted the new placeholder (`"1..5"`). The instruction is not a reliable lever for absence.
- **Physical dimensions are polluted.** Die size is prose (`Die size: 4530 µm x 6090 µm`). The model reads the `(+0/-50 µm)` tolerance as a range and fabricates a `max`, varies run-to-run, and parrots the instruction's `9.00 x 8.00 mm` example when asked for `size`.

The pattern across all three: on this weak model, **deterministic code is a strong lever and instruction wording is a weak one**. These findings are recorded in the *Findings beyond this change's scope* section of `improve-datasheet-pdf-text/design.md`; this change acts on them.

## What Changes

- **VDD / supply synonym recognition.** Teach extraction that a datasheet's `Drain Voltage`, `Vds`, `Drain to Source Voltage`, `Vcc`, or `Collector Voltage` satisfies a request for `VDD`/`VCC`.
- **Categorical grounding check (anti-hallucination).** A deterministic post-extraction check: if a requested categorical parameter's keyword does not appear in the fed datasheet text, its value is forced to `null`. The model is never trusted to return `null` on absence.
- **Deterministic dimension parser.** Physical-size prose (`A x B unit`) is parsed with a regex, bypassing the model for this structured pattern. Product-resolved convention: the **first dimension is length, the second is width**.
- **No breaking change to the extraction contract shape.** The `{unit, min, typ, max, value, condition}` / `null` result shape is unchanged; these are input-mapping and output-grounding refinements.

## Capabilities

### Modified Capabilities

- `datasheet-extraction`: the extraction requirements gain (a) synonym recognition for supply-voltage wording, (b) a deterministic absence-grounding rule for categorical parameters, and (c) a deterministic dimension parser for physical size. The PDF-to-text requirements (owned by `improve-datasheet-pdf-text`) are untouched.

## Impact

- **Code:** `rf_finder/datasheet/extractor.py` and `rf_finder/datasheet/mapping.py`; possibly a bounded, measured synonym addition to `EXTRACT_RF_PARAMETERS_INSTRUCTION` (kept minimal — the grounding and dimension work is in code, not wording).
- **Tests:** `tests/test_datasheet_extractor.py` (or the existing extractor test module) — the grounding check and dimension parser are pure and unit-testable without a model; synonym behaviour is verified against the `evals/pdfs/` datasheets.
- **Dependencies:** none added.
- **Relationship:** complements `improve-datasheet-pdf-text`, which improves the *text*; this change improves the *interpretation*. Operating/storage temperature already extracts correctly and needs nothing here.
- **Out of scope:** the pdf.py rendering/segmentation pipeline (the companion change); the multi-value Typ-cell / condition-column rendering question (a pdf.py concern); the provider/model choice and `num_ctx` in `rf_finder.config` (measured as not the cause).
