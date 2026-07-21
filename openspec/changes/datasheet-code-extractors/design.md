## Context

`extract_rf_parameters` extracts four datasheet parameters via the local LLM.
Measurement this cycle showed the LLM is non-deterministic in practice (cold vs
warm model-load state changes the answer even at `temperature=0`) and fails
silently (plausible-but-wrong) on explicit fields. For the three explicit
parameters — TEMPERATURE, SIZE, MSL — a deterministic regex matched the
source-verified gold better: TEMP 7/7 and SIZE 7/7, plus MSL and fix validation
against a 32-datasheet MD5-deduped corpus with per-value source evidence. The
regex logic exists only as scratchpad prototypes (`temp_v2.py`, `size_v2.py`,
`extractors.py`) and a scratchpad pytest; it is not in the product or test suite.

## Goals / Non-Goals

**Goals:**
- Land the validated regex extractors as a deterministic, model-free layer in
  `rf_finder/datasheet/`, with a small stable API: `temp_range`, `size_dims`,
  `msl_level`.
- Guarantee "loud" failure: return `None` on absence, never a silent guess.
- Cover the behavior with repo tests over diverse, source-verified datasheets.

**Non-Goals:**
- VDD extraction (remains the LLM/hybrid path).
- Wiring the layer into `extract_rf_parameters` or the evaluator as code-first
  with LLM fallback (separate follow-up change).
- Table/OCR extraction for values absent from the extracted text (a PDF-text
  problem, not a regex one).

## Decisions

**1. Anchor-then-decode, not free-form value search.**
Each extractor locates a labeled region (operating-temp label, `A×B` with a size
signal, MSL anchor) and decodes the value from it in code. Regex locates; code
decodes. This keeps precision high and makes every `None` explainable (no anchor
matched). Alternative — one broad value regex per parameter — was rejected: it
over-captured graph captions and mechanical callouts in measurement.

**2. Number acceptance is signed-or-unit-adjacent.**
TEMPERATURE numbers are accepted only when signed (`+`/`-`/en/em dash) or
immediately followed by a temperature unit. This was the fix that dropped a
footnote superscript ("Operating Temperature5") and still accepts an unsigned
upper bound that carries the unit ("-40 105 °C"). Alternative — a lookbehind for
a non-letter — failed when the footnote had a space.

**3. Standalone-digit scan for MSL.**
MSL takes the first 1–6 digit that is not part of a larger number, so reflow
temperatures (260/150/320) interleaved with the MSL text are skipped while a real
"... Reflow 260 °C ... 3" still yields 3. Alternative — first digit within N
chars — grabbed the leading digit of the reflow temperature.

**4. Promote scratchpad logic verbatim where validated.**
The regex bodies move as-is (they are already measured); only packaging changes
(module location, one public API). No behavioral rewrite, to preserve the 7/7
gold results.

## Risks / Trade-offs

- **Corpus-tuned regex may miss a novel vendor format.** → Acceptable because it
  fails loud (`None`), which the follow-up LLM-fallback layer can catch; growth is
  driven by adding source-verified gold, not by loosening anchors.
- **Values absent from the extracted PDF text return `None` even when present in a
  table/image.** → Out of scope here; this is a PDF-text extraction limitation,
  surfaced honestly as `None`.
- **Self-authored gold.** → Mitigated by verifying every gold value against the
  raw source text (grep evidence) before it enters a test.

## Open Questions

- Final module name/location under `rf_finder/datasheet/` (e.g.,
  `code_extractors.py`) — resolve in tasks.
- Whether to merge into the existing `tests/test_datasheet_extractor.py` or add a
  sibling `tests/test_datasheet_extractors.py`.
