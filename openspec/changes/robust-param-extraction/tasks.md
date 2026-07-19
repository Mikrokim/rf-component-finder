## 1. Supply-voltage alias map + prompt injection

- [ ] 1.1 Add `_PARAM_ALIASES` to `rf_finder/datasheet/extractor.py`: `{"VDD": ["Drain Voltage", "Vds", "Drain to Source Voltage"], "VCC": ["Vcc", "Collector Voltage"]}`.
- [ ] 1.2 In `extract_rf_parameters`, build an aliases sub-map for the requested names that have entries and expose it to the model (an `aliases` key in the input plus one generic instruction line: treat a listed alias as its parameter). Keep the instruction addition bounded and measured. (spec: *Requested supply-voltage names are matched under vendor wording*)

## 2. Categorical grounding check (pure, code)

- [ ] 2.1 Add `_CATEGORICAL_KEYWORDS = {"MSL": ["msl", "moisture"], "package": ["package", "pkg", "case", "outline", "body"]}` — data-derived from the five surveyed vendors; `jedec` deliberately excluded (it marks ESD/package standards, not MSL).
- [ ] 2.2 Add `_ground_categorical(name, spec, datasheet_text)`: if `name` is keyword-grounded and none of its keywords appears (case-insensitively) in `datasheet_text`, return `None`; otherwise return `spec` unchanged. (spec: *An absent keyword-grounded parameter is never fabricated*)

## 3. Deterministic dimension parser (pure, code)

- [ ] 3.1 Add `_DIM_RE` and `_parse_dimensions(text) -> tuple[dict | None, dict | None]`: match `A x B unit` (tolerant of `x`/`×` and an optional repeated unit); the first number → `length`, the second → `width`, each with its unit; no match → `(None, None)`. (spec: *Physical size prose is decomposed into length and width*)
- [ ] 3.2 In `extract_rf_parameters`, when `length`/`width` are requested, override the model's answer with `_parse_dimensions` — deterministic, bypassing the model.

## 4. Wire into extract_rf_parameters

- [ ] 4.1 Apply in order: alias injection (task 1) before the model call; then on the result — dimension override (task 3) and categorical grounding (task 2); preserve the `{unit, min, typ, max, value, condition}` / `None` shape and the exactly-requested-keys contract. `datasheet_text` is already a parameter of `extract_rf_parameters` — no signature change.

## 5. Verify

- [ ] 5.1 Unit tests (no model) in `tests/test_datasheet_extractor.py`: `_parse_dimensions` (`"4530 µm x 6090 µm"` → 4530 / 6090; `×` and repeated-unit variants; no-pattern → `None`/`None`); `_ground_categorical` (keyword present → kept, absent → `None`); `_PARAM_ALIASES` lookup.
- [ ] 5.2 Integration over `evals/pdfs/`: VDD on CMPA (stated as `Drain Voltage`) → `{"typ": 28}`; MSL → `"3"` (ADCA3270), `"1"` (GRF2111), `null` (CMPA, absent); length/width on CMPA → 4530 / 6090.
- [ ] 5.3 Run the full test suite; confirm existing extractor tests and the contract shape are unaffected.
