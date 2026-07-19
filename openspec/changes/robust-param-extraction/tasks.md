## 1. Supply-voltage alias map + prompt injection

- [x] 1.1 Add `_PARAM_ALIASES` to `rf_finder/datasheet/extractor.py`: `{"VDD": ["Drain Voltage", "Vds", "Drain to Source Voltage"], "VCC": ["Vcc", "Collector Voltage"]}`.
- [x] 1.2 In `extract_rf_parameters`, build a per-call instruction: append a `SYNONYMS:` hint listing the aliases of any requested name that has a `_PARAM_ALIASES` entry, leaving the module-level instruction unchanged. (measured: VDD `{}` → `{"typ": 28}`) (spec: *Requested supply-voltage names are matched under vendor wording*)

## 2. Categorical grounding check (pure, code)

- [x] 2.1 Add `_CATEGORICAL_KEYWORDS = {"MSL": ["msl", "moisture"], "package": ["package", "pkg", "case", "outline", "body"]}` — data-derived from the five surveyed vendors; `jedec` deliberately excluded (it marks ESD/package standards, not MSL).
- [x] 2.2 Add `_ground_categorical(name, spec, datasheet_text)`: if `name` is keyword-grounded and none of its keywords appears (case-insensitively) in `datasheet_text`, return `None`; otherwise return `spec` unchanged. (spec: *An absent keyword-grounded parameter is never fabricated*)

## 3. Deterministic dimension parser (pure, code)

- [x] 3.1 Add `_DIM_RE` and `_parse_size_spec(size_spec, datasheet_text) -> tuple[dict | None, dict | None]`: split the model's `size` answer — an `A x B` string in `value` (tolerant of `x`/`×` and an optional repeated unit), else its `min`/`max` pair — into `length` (first) and `width` (second); ground the pair against real `A x B` pairs in the datasheet text; no usable/grounded pair → `(None, None)`. (spec: *The model's size answer is split into length and width*)
- [x] 3.2 In `extract_rf_parameters`, add `size` to the model request when `length`/`width` are requested, split the model's `size` answer via `_parse_size_spec`, and return only the caller's requested keys (drop the internally-added `size`).

## 4. Wire into extract_rf_parameters

- [x] 4.1 Apply in order: alias injection (task 1) before the model call; then on the result — dimension override (task 3) and categorical grounding (task 2); preserve the `{unit, min, typ, max, value, condition}` / `None` shape and the exactly-requested-keys contract. `datasheet_text` is already a parameter of `extract_rf_parameters` — no signature change.

## 5. Verify

- [x] 5.1 Unit tests (no model) in `tests/test_datasheet_extractor.py`: `_parse_size_spec` (from a `value` string → 4530 / 6090; from a `min`/`max` pair; ungrounded hallucination → `(None, None)`; `None` input → `(None, None)`); `_ground_categorical` (keyword present → kept, absent → `None`, non-categorical passthrough); `_PARAM_ALIASES` lookup; plus wiring through `extract_rf_parameters` (the model's `size` split into length/width, ungrounded size nulled, `size` not leaked, categorical grounding, alias-hint injection). All pass.
- [ ] 5.2 Integration over `evals/pdfs/`: VDD on CMPA (stated as `Drain Voltage`) → `{"typ": 28}`; MSL → `"3"` (ADCA3270), `"1"` (GRF2111), `null` (CMPA, absent); length/width on CMPA → 4530 / 6090.
- [ ] 5.3 Run the full test suite; confirm existing extractor tests and the contract shape are unaffected.
