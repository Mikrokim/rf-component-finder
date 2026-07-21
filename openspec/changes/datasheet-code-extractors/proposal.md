## Why

Three of the four datasheet parameters (TEMPERATURE, SIZE, MSL) are explicit,
uniform facts that a deterministic regex extracts more reliably than the LLM:
measured TEMP 7/7 and SIZE 7/7 on the gold set, and validated against a
32-datasheet MD5-deduped corpus. Regex fails **loud** (returns `None` when a value
is absent), whereas the LLM fails **silent** (plausible-but-wrong) and is
non-deterministic in practice. Today this validated logic lives only in scratchpad
prototypes, so it is neither part of the product nor covered by the test suite.

## What Changes

- Add a deterministic, no-model extraction layer under `rf_finder/datasheet/`
  exposing `temp_range(text)`, `size_dims(text)`, `msl_level(text)`.
- **TEMPERATURE**: anchor on `operating`/`operation` `temperature`/`range`
  (incl. `case`/`junction`/`ambient` and the abbreviation `Temp.`), with a tier-2
  fallback to a bare `Temperature Range` only when its left context is not a
  storage/junction/mounting/reflow label; normalize the PDF private-use degree
  glyph `U+F0B0`→`°`; accept only signed or unit-adjacent numbers (skips footnote
  superscripts); treat en/em dash as a minus sign.
- **SIZE**: `A×B` requiring a length unit OR a size keyword
  (package/die/chip/size) with no distractor (thru-hole/diameter/tolerance/bond
  pad/MTTF/hours/×10); reject zero dimensions; support curly-quote inches.
- **MSL**: anchor `moisture sensitivity`/`MSL` then the first **standalone** 1–6
  digit (skips reflow temperatures such as 260/150 whose leading digit was
  previously misread as the level).
- Add `tests/` coverage over 4 diverse, source-verified datasheets × 3 params
  (grf2111, adca3270, am06013033wm, RWLA1001).

## Capabilities

### New Capabilities
- `datasheet-code-extraction`: deterministic, regex-only extraction of the
  explicit datasheet parameters (TEMPERATURE, SIZE, MSL) from datasheet text,
  returning a value or `None` (never a silent guess), independent of any model.

### Modified Capabilities
<!-- None. VDD and wiring code-first-with-LLM-fallback into extract_rf_parameters
     are explicitly out of scope for this change. -->

## Impact

- **New code**: `rf_finder/datasheet/` gains a code-extractor module (the
  validated regex logic promoted from scratchpad `temp_v2.py` / `size_v2.py` /
  `extractors.py`).
- **New tests**: `tests/test_datasheet_extractors.py` (4 datasheets × 3 params).
- **No behavior change** to `extract_rf_parameters` or the evaluator yet — this
  change only lands the deterministic layer and its tests. Wiring it in as
  code-first with LLM fallback, and adding VDD, are separate follow-up changes.
- **Dependencies**: none new (pure `re` + existing `datasheet_text_from_pdf`).
