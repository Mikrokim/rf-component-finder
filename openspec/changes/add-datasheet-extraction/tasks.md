# Tasks — Retroactive capture of `datasheet-extraction`

These are DOCUMENTATION / VERIFICATION tasks: the feature code already exists and is tested. No feature code is written or changed. Each task confirms a spec requirement against its cited code and passing test.

## 1. Confirm the tests are green

- [x] 1.1 Run `pytest tests/test_datasheet_pdf.py tests/test_datasheet_extractor.py tests/test_datasheet_mapping.py` and confirm all pass (26 passed).

## 2. Verify PDF-to-text requirement

- [x] 2.1 Verify "Extract datasheet text from a PDF" against `rf_finder/datasheet/pdf.py` (`_text_from_stream`, `_join_page_text`).
- [x] 2.2 Confirm each scenario maps to a passing test in `tests/test_datasheet_pdf.py`: blank-line join (`test_pages_are_joined_with_blank_line`), skip empty/None (`test_empty_and_none_pages_are_skipped`), empty string (`test_no_extractable_text_gives_empty_string`), missing path (`test_missing_path_raises_file_not_found`).

## 3. Verify extraction contract + invocation requirements

- [x] 3.1 Verify "Datasheet extraction contract and invocation" against `extractor.py` (`EXTRACT_RF_PARAMETERS_INSTRUCTION`, `extract_rf_parameters`) and `config.py` (`DATASHEET_MODEL`, `DATASHEET_PROVIDER`).
- [x] 3.2 Confirm scenarios map to `test_run_receives_instruction_and_both_context_keys` and `test_model_comes_from_config_variable_not_a_parameter`.

## 4. Verify output-contract-enforcement requirement

- [x] 4.1 Verify "Extraction output contract enforcement" against `extract_rf_parameters` / `_normalize_spec`.
- [x] 4.2 Confirm scenarios map to `test_found_and_not_found_parameters`, `test_key_the_model_omitted_comes_back_as_none`, `test_extra_key_the_model_invented_is_dropped`, `test_categorical_value_field_passes_through`, `test_discrete_supply_list_value_passes_through`.

## 5. Verify reply-cleanup and error-path requirements

- [x] 5.1 Verify "Model reply cleanup" against `_extract_json_object`; confirm `test_markdown_fences_are_stripped` and `test_thinking_model_preamble_is_stripped`.
- [x] 5.2 Verify "Extraction error handling" against the `result.success` / `json.loads` paths; confirm `test_provider_failure_raises_runtime_error` and `test_invalid_json_raises_value_error_with_raw_output`.

## 6. Verify mapping requirements

- [x] 6.1 Verify "Map extracted specs to RawValue by comparison rule" against `mapping.py` (`to_raw_params`, `_to_value`); confirm `test_min_comparison_takes_guaranteed_min`, `test_max_comparison_takes_guaranteed_max`, `test_min_comparison_ignores_opposite_end_max`, `test_max_comparison_ignores_opposite_end_min`, `test_contains_range_becomes_low_high_tuple`, `test_contains_discrete_list_stays_a_list`.
- [x] 6.2 Verify "Unit reconciliation and number parsing in mapping" against `_normalize_unit` / `_numbers`; confirm `test_size_string_parses_to_largest_dimension`, `test_msl_string_parses_to_number_with_canonical_unit`.
- [x] 6.3 Verify "Skip unmappable and unknown parameters"; confirm `test_not_found_and_unknown_names_are_skipped`.
- [x] 6.4 Verify "Mapped parameters verify through the real Verifier"; confirm `test_mapped_params_verify_against_real_verifier` (overall `match`, confidence `datasheet`) and `test_mapped_gain_can_fail_when_below_requirement`.

## 7. Validate the change artifacts

- [x] 7.1 Run `openspec validate add-datasheet-extraction --strict` and fix any spec-wording issues (never code).

## 8. Archive-time updates (do NOT do now — happens during archive)

- [ ] 8.1 Update `openspec/future-requirements.md` REQ-2.2 and the iteration-2 "Datasheet-only parameters" note from "Not implemented" to "module implemented (see `datasheet-extraction`), integration pending", and cross-reference from `manufacturer-adapters` if appropriate.
