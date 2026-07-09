# Datasheet Extraction Specification

Documents the datasheet parameter-extraction module (`rf_finder/datasheet/`) **as currently implemented and verified** by `tests/test_datasheet_pdf.py`, `tests/test_datasheet_extractor.py`, and `tests/test_datasheet_mapping.py`. The module is a standalone layer with three primitives — PDF-to-text, the LLM extraction contract, and the extractor-output-to-`RawValue` mapping. It is NOT wired into any adapter or the search pipeline; integration remains future work.

## ADDED Requirements

### Requirement: Extract datasheet text from a PDF

The system SHALL provide `datasheet_text_from_pdf(path, *, pages=None)` which opens a datasheet PDF with `pdfplumber` and returns its page text joined into a single string. `pages=None` SHALL read every page; a list of 0-based page indices SHALL restrict extraction to those pages. Pages that yield no text or whitespace-only text SHALL be skipped, and non-empty pages SHALL be separated by a blank line (`\n\n`). When no page yields extractable text the result SHALL be the empty string. The function SHALL raise `FileNotFoundError` when the path does not exist.

#### Scenario: Pages are joined with a blank line

- **WHEN** `_join_page_text` is given pages whose text is `"PAGE ONE"` and `"PAGE TWO"`
- **THEN** the result is `"PAGE ONE\n\nPAGE TWO"`

#### Scenario: Empty and text-less pages are skipped

- **WHEN** the pages yield `"REAL"`, `None`, `"   "`, and `"MORE"`
- **THEN** the result is `"REAL\n\nMORE"` (no blank blocks for the skipped pages)

#### Scenario: No extractable text gives an empty string

- **WHEN** every page yields `None` or `""`
- **THEN** the result is the empty string `""`

#### Scenario: Missing PDF path raises FileNotFoundError

- **WHEN** `datasheet_text_from_pdf` is called with a path that does not exist
- **THEN** it raises `FileNotFoundError`

### Requirement: Datasheet extraction contract and invocation

The system SHALL publish `EXTRACT_RF_PARAMETERS_INSTRUCTION` as the stable extraction contract: the model receives a Context with exactly two keys — `datasheet` (raw text) and `requested_parameters` (a list of names) — and must return ONLY a JSON object with exactly one key per requested name (the name verbatim), each value being either a `{unit, min, typ, max, value, condition}` object or JSON `null` when the datasheet does not state the parameter; guessing or inferring is forbidden. `extract_rf_parameters(datasheet_text, requested_parameters, provider=None, runtime=None)` SHALL invoke the runtime with this instruction verbatim, with both context keys populated from its arguments, with the model taken from `DATASHEET_MODEL` in `rf_finder.config` (NOT a parameter), and with the provider defaulting to `DATASHEET_PROVIDER` (overridable per call). The named parameters inside the contract are illustrative categories, not an exhaustive list.

#### Scenario: Run receives the instruction and both context keys

- **WHEN** `extract_rf_parameters("DATASHEET TEXT", ["gain"])` runs against an injected runtime
- **THEN** the run's `instruction` equals `EXTRACT_RF_PARAMETERS_INSTRUCTION`
- **AND** the run's `provider` is `"local"` (from `DATASHEET_PROVIDER`)
- **AND** the run's `input` is `{"datasheet": "DATASHEET TEXT", "requested_parameters": ["gain"]}`

#### Scenario: Model comes from config, not a parameter

- **WHEN** `extract_rf_parameters` runs
- **THEN** the run's `model` is `"qwen3:8b"` (from `DATASHEET_MODEL`)

### Requirement: Extraction output contract enforcement

`extract_rf_parameters` SHALL return a dict containing exactly one key per requested parameter name regardless of what the model returned. A found parameter SHALL be normalized to the full six-field shape `{unit, min, typ, max, value, condition}` with any missing field set to `None`; a not-found parameter SHALL be `None` (not `{}`); and any extra key the model invented SHALL be dropped. Categorical values and discrete option lists carried in the `value` field SHALL pass through unchanged.

#### Scenario: Found and not-found parameters are returned as given

- **WHEN** the model returns a full `gain` object and `noise_figure: null` for requested `["gain", "noise_figure"]`
- **THEN** the result maps `gain` to that object and `noise_figure` to `None`

#### Scenario: A key the model omitted comes back as None

- **WHEN** requested parameters are `["gain", "impedance"]` but the model returns only `gain`
- **THEN** the result includes `impedance` mapped to `None`

#### Scenario: An extra key the model invented is dropped

- **WHEN** the model returns `gain` plus an unrequested `hallucinated` key for requested `["gain"]`
- **THEN** the result contains only `gain`

#### Scenario: Categorical value field passes through

- **WHEN** the model returns MSL `value: "3"` and Size `value: "9.00 x 8.00 mm"` (numeric fields null)
- **THEN** those objects are returned unchanged with their `value` strings intact

#### Scenario: Discrete supply list value passes through

- **WHEN** the model returns a VDD object with `value: [3, 5, 8]`
- **THEN** the returned VDD object's `value` is `[3, 5, 8]`

### Requirement: Model reply cleanup

Before parsing, `extract_rf_parameters` SHALL recover the JSON object from a model reply that wraps it in noise: a `<think>...</think>` reasoning preamble SHALL be stripped, surrounding markdown code fences (including a leading `json` tag) SHALL be removed, and as a last resort the text SHALL be sliced from the first `{` to the last `}`.

#### Scenario: Markdown fences are stripped

- **WHEN** the model wraps its JSON object in a ` ```json ... ``` ` fence
- **THEN** the object is parsed and returned as if unfenced

#### Scenario: Thinking-model preamble is stripped

- **WHEN** the model emits a `<think>...</think>` reasoning preamble before the JSON object
- **THEN** the preamble is discarded and the object is parsed and returned

### Requirement: Extraction error handling

`extract_rf_parameters` SHALL raise `RuntimeError` when the LLM run reports failure, and SHALL raise `ValueError` when the model's output is not valid JSON.

#### Scenario: Provider failure raises RuntimeError

- **WHEN** the runtime reports the run failed (e.g. `"quota exceeded"`)
- **THEN** `extract_rf_parameters` raises `RuntimeError` carrying the failure message

#### Scenario: Invalid JSON raises ValueError

- **WHEN** the model returns prose that is not valid JSON (e.g. `"The gain is 22 dB."`)
- **THEN** `extract_rf_parameters` raises `ValueError` referencing invalid JSON

### Requirement: Map extracted specs to RawValue by comparison rule

The system SHALL provide `to_raw_params(params)` converting extractor output (keyed by ontology canonical names) into `{canonical_name: RawValue}` for the Verifier, choosing the `RawValue` shape from each parameter's ontology `comparison` rule. For `contains` (e.g. freq_range, VDD, Temperature): an explicit discrete list SHALL become a list of numbers, a continuous `min`+`max` SHALL become a `(low, high)` tuple, and otherwise a two-ended "A to B" string with at least two numbers SHALL become `(min, max)`. For `min` (e.g. Gain): the guaranteed value SHALL be the stated `min`, falling back to `typ`, and MUST NOT borrow the opposite end (`max`) — a spec with only `max` SHALL be left out (Verifier UNKNOWN). For `max` (e.g. NF, Size): the stated `max`, falling back to `typ`, never borrowing `min`. For `eq`: `typ`, then `min`/`max`, then the first parsed number.

#### Scenario: min comparison takes the guaranteed min

- **WHEN** a Gain spec has `min=22.0, typ=23.6, max=25.0` (comparison `min`)
- **THEN** the mapped `RawValue` is `RawValue(value=22.0, unit="dB")`

#### Scenario: max comparison uses typ when no max is stated

- **WHEN** an NF spec has only `typ=3.0` (comparison `max`)
- **THEN** the mapped `RawValue` is `RawValue(value=3.0, unit="dB")`

#### Scenario: min comparison ignores the opposite-end max

- **WHEN** a Gain spec has only `max=25.0` (no `min`, no `typ`)
- **THEN** `Gain` is absent from the mapped result (left UNKNOWN, not borrowed from `max`)

#### Scenario: max comparison ignores the opposite-end min

- **WHEN** an NF spec has only `min=1.0` (no `max`, no `typ`)
- **THEN** `NF` is absent from the mapped result (left UNKNOWN, not borrowed from `min`)

#### Scenario: contains range becomes a (low, high) tuple

- **WHEN** a Temperature spec has `min=-30, max=110` (comparison `contains`)
- **THEN** the mapped `RawValue` is `RawValue(value=(-30.0, 110.0), unit="degC")`

#### Scenario: contains discrete list stays a list

- **WHEN** a VDD spec has `value=[3, 5, 8]` (comparison `contains`)
- **THEN** the mapped `RawValue` is `RawValue(value=[3.0, 5.0, 8.0], unit="V")`

### Requirement: Unit reconciliation and number parsing in mapping

`to_raw_params` SHALL reconcile stated units to the ontology's canonical spelling — `C`/`°C`/`degrees C` become `degC` and `Ohms` becomes `Ohm`. When a `value` carries no unit (empty or missing), `to_raw_params` SHALL fill the parameter's canonical unit ONLY when the parameter is unambiguous — it has a single accepted unit (`len(units) == 1`), which covers dimensionless parameters (e.g. MSL, canonical `""`) and single-unit ones (e.g. Gain → `dB`). For a multi-unit parameter (e.g. `freq_range` GHz/MHz, `P1dB`/`Psat` dBm/W/mW) a missing unit is ambiguous, so `to_raw_params` SHALL NOT guess the unit — it SHALL omit the parameter (leaving it UNKNOWN) rather than assume the canonical unit. Numbers SHALL be parsed out of free-text `value` strings; for a `max`-rule dimension string the worst-case (largest) number SHALL be used.

#### Scenario: A single-unit parameter's missing unit is filled with the canonical unit

- **WHEN** a Gain spec (accepted units `["dB"]`) has `min=22.0` and no unit
- **THEN** the mapped `RawValue` is `RawValue(value=22.0, unit="dB")` (unambiguous, so filled)

#### Scenario: A multi-unit parameter's missing unit is not guessed

- **WHEN** a `freq_range` spec (accepted units `["GHz", "MHz"]`) has a value but no unit
- **THEN** `freq_range` is absent from the mapped result (left UNKNOWN, not assumed `GHz`)

#### Scenario: Size string parses to the largest dimension

- **WHEN** a Size spec (comparison `max`) has `value="9.00 x 8.00 mm"`
- **THEN** the mapped `RawValue` is `RawValue(value=9.0, unit="mm")` (worst-case dimension)

#### Scenario: MSL string parses to a number with the canonical unit

- **WHEN** an MSL spec has `value="3"` and no unit
- **THEN** the mapped `RawValue` is `RawValue(value=3.0, unit="")` (canonical unit filled in)

### Requirement: Skip unmappable and unknown parameters

`to_raw_params` SHALL omit any parameter the ontology does not define, any not-found (`None`) spec, and any spec from which no value can be formed, so the Verifier reports those constraints as UNKNOWN rather than mis-comparing them.

#### Scenario: Not-found and unknown names are skipped

- **WHEN** `params` is `{"Gain": None, "not_an_ontology_param": {...typ=5...}}`
- **THEN** `to_raw_params(params)` returns `{}`

### Requirement: Mapped parameters verify through the real Verifier

Parameters mapped by `to_raw_params` SHALL be consumable by `verify()` unchanged: a candidate with `source="datasheet"` whose `raw_params` come from the mapping SHALL produce per-parameter verdicts and an overall outcome with `confidence == "datasheet"`, and SHALL be able to FAIL a constraint the mapped value does not satisfy.

#### Scenario: Mapped params verify to an overall match with datasheet confidence

- **WHEN** Gain (`min=22.0`), NF (`typ=3.0`), Temperature (`min=-30, max=110`), and Size (`"9.00 x 8.00 mm"`) are mapped onto a `source="datasheet"` candidate and checked against Gain>=20 dB, NF<=4 dB, Temperature contains (0, 85) degC, and Size<=10 mm
- **THEN** every verdict is `PASS`, the overall outcome is `match`, and the confidence is `"datasheet"`

#### Scenario: A mapped Gain fails when below the requirement

- **WHEN** a Gain of guaranteed `22.0 dB` is checked against a `min` requirement of `24.0 dB`
- **THEN** the Gain verdict is `FAIL` and the overall outcome is `fail`
