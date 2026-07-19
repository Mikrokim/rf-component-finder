## Context

`rf_finder/datasheet/pdf.py` is 53 lines: open a PDF with `pdfplumber`, call `page.extract_text()` on each page, join the non-empty ones with `\n\n`. That output is the entire input to the LLM extractor, and measurement shows it is where the extraction errors are born.

The findings that constrain this design were all measured on real datasheets with `temperature=0` (so results are reproducible) against five vendors — MACOM, Analog Devices, Guerrilla RF, Hittite, AMCOM:

- **Flattened tables cause mis-filed fields.** `extract_text()` orders glyphs y-then-x, so a spec table's cells interleave and the column a number sat under is unrecoverable. Changing only the text — nothing else — moved Drain Voltage from `{"min": 28, "max": 28}` to the correct `{"typ": 28}`.
- **Whole-document context is worse than a focused page, even when it fits.** Full document at `num_ctx=8192`: 5,370/8,192 tokens, no truncation, 323s — and `length`/`width` came back `null`. The relevant page alone: correct values in ~20s. The remedy is less context, not more window.
- **Cleanup alone is not the fix.** Furniture de-duplication saves 45% on one vendor and 4% on another. It is worth doing and it is not a solution.

The consuming model is the constraint. A small local model (`llama3.1:8b`, 2048-token default window) both dilutes easily and follows rules poorly; the cloud model has a 1M window but has been unreachable from this network for parts of the investigation. The design must serve a weak, small-window reader.

## Goals / Non-Goals

**Goals:**

- Preserve the column structure of specification tables so a number's field (min/typ/max) is recoverable rather than guessed.
- Remove repeated page furniture without losing the specs it carries.
- Offer the datasheet as focused, budget-sized, relevance-ordered segments.
- Keep `datasheet_text_from_pdf(path, pages=None)` behaviour-compatible for existing callers.
- Add no dependency, and keep every new unit of logic testable with fake pages, as `_join_page_text` already is.

**Non-Goals:**

- **Deciding how segments are consumed.** Whether the extractor takes one segment or iterates all of them, and how several results merge, is `extractor.py`'s concern and a separate decision. This module produces; it does not orchestrate.
- Changing `EXTRACT_RF_PARAMETERS_INSTRUCTION`, the provider/model in `config.py`, or Ollama's `num_ctx`.
- Detecting performance-curve pages (see Risks — it cannot be done reliably today).
- Suppressing evaluation-board / BOM sections (deferred until verified).
- OCR of image-only pages, or reading values out of plotted curves.

## Decisions

### Render each detected table as a pipe table in place; fall back to layout mode

Measurement (five vendors, `llama3.1:8b`, `temperature=0`) selected a hybrid over plain layout mode. For each page: detect tables with `find_tables()`, extract each cell by its own bbox, and re-render the table as a `| Parameter | Units | Min. | Typ. | Max. |` **pipe table** in place, with the page's remaining prose interleaved around it in reading order. A per-page content-preservation guard (below) falls the page back to `extract_text(layout=True)` if the rendering would drop any source token.

*Why pipe, measured.* Three renderings were compared for content preservation and size across all five datasheets:

- **pipe** — lost 1.19% of source tokens (almost entirely plot axis-labels, not spec data), fell back on 12 of 73 pages, ran ×1.04 the size of plain flattened text (×0.17 of layout mode).
- **key=value** — lost 1.32%, fell back on 23 pages, ×1.07; it also silently drops the header-label words it consumes as keys.
- **layout-only** — preserves content but inflates the text ×3–5 *in characters*, which starves the small model's window and dilutes context.

*Characters overstate the gap; the model pays in tokens.* Those size figures are characters. In `llama3.1:8b` tokens the spread is far tighter — CMPA p1: plain 459, pipe 543 (×1.18, +84 tokens), layout 645 (×1.41). Pipe's `|` delimiters each cost a token, while layout's padding spaces tokenise cheaply, so the ×3–5 character inflation is only ×1.41 in tokens. Pipe therefore costs ~18% more tokens than flattened text — still fewer than layout, but not the near-free the character ratio implies.

Pipe wins on **correctness, not size**: it recovers correct column placement (Drain Voltage `{"value":"28"}` → `{"typ":28}`) while staying cheaper in tokens than the layout fallback. On a single focused page all three fit the window, so token cost is not the deciding factor there — it bites only when many pages are concatenated.

*Why per-cell bbox.* An earlier hybrid filtered prose by the *whole table's* bbox and lost real parameters (P1dB, Gain) that `find_tables()` claimed but did not extract. The fix is to remove a word from prose only when it sits inside an *extracted cell's* bbox — a word inside the table rectangle but outside every cell stays in prose, so nothing falls between the two.

*Alternatives considered.* `extract_tables()` alone returns a cell grid but **drops all prose** — on CMPA p0 it loses the Features bullet `IM3: <-25 dBc at 44 dBm Pout`; the per-cell hybrid keeps prose by construction. `pymupdf4llm` is purpose-built for PDF→Markdown-for-LLM but is **AGPL-3.0**: distributing the product or offering it as a network service triggers source-disclosure obligations. That is a business decision, not a technical one, and the free path already recovers the measured benefit — so it is rejected for this change and can be revisited if a gap remains.

### Guard content preservation; fall back per page

After rendering a page, tokenise the source `extract_text()` and the rendering (technical tokens only — scaffolding `|` and `=` are ignored) and require the source's token multiset to be a subset of the rendering's. A page that loses any token falls back to `extract_text(layout=True)`, which is proven to preserve content. The guard detects *lost* content, not *added* junk (that is the empty-table filter's job) — the two are complementary. Measured: 12 of 73 pages fall back under pipe, almost all plot/curve pages that carry no extractable table anyway.

### Drop tables that are mostly empty; release their cells to prose

`find_tables()` mis-detects a plot's gridlines as a table and emits a grid of near-empty cells. A detected table whose cells are less than ~25% filled is treated as not-a-table: it is dropped and its bboxes are **not** claimed, so any real text under it returns to prose. Within a kept table, a row with zero filled cells is dropped. This is lossless by construction — an empty cell carries no data — and the content-preservation guard runs after it as a backstop. Measured: junk rows leaking onto guard-passing pages fell from 116 to 8, and every other metric improved with it (token loss 1.45→1.19%, fallbacks 17→12, size ×1.19→×1.04).

### Give a headerless table the header of its sibling, aligned by column x-position

Some spec tables have no header of their own: on CMPA the DC-electrical table's top row is literally empty, because the vendor printed `Min | Typ | Max` once, above the AC table. Without a header the small model reads each row's middle value inconsistently (Drain Voltage → `typ:28`, but Gate Voltage → `min:-2`). The fix: when a detected table has no header row, borrow the nearest preceding header table's labels, matching each column to the x-nearest donor column. Measured: with the propagated header, Drain / Gate / Quiescent voltage all return a consistent `typ`. Still unsolved (see Open Questions): the wide, empty-headed **condition column** on the AC table mis-aligns the model — it reads the Typ column as Max even for single-valued rows — and a Typ cell holding several per-frequency values (`47.4 47.9 47.6`) is not yet rendered as an unambiguous list.

### De-duplicate furniture; never delete it

A line on ≥80% of pages is furniture. We keep its **first** occurrence.

The naive rule — drop every occurrence — was rejected on evidence: the banner states the frequency range in **four of the five** datasheets (`75Ω 45 to 1218 MHz`, `13.75 - 15.5 GHz`, `8 to 12 GHz Useable`, `8 - 14 GHz`) and power ratings (`60 W`, `2 Watt`). Deleting it would silently destroy parameters available nowhere else. Keeping one copy costs ~3% and saves ~42%.

The 80% threshold, and the ≥4-page floor below which de-duplication is skipped, are judgement calls: on the surveyed set every real furniture line sits at 89–100% and the nearest non-furniture line is at 44%, so the gap is wide and the exact cut is not delicate.

### Guard table headers with a narrow keyword list, not geometry

A repeated spec-table header must never be collapsed — that would destroy the very column context the pipe rendering exists to mark. Any line matching `min|max|typ|nom|typical|minimum|maximum|nominal|parameter|units?|symbol|conditions?|rating|value` is exempt from de-duplication.

*Verified on all five vendors:* the guard matches **none** of the 33 real furniture lines (so it costs no savings) and **every** real table header (so it protects all of them) — including headers phrased `Parameter Symbol Min Typ Max Unit Test Conditions/Comments`, `Parameters Minimum Typical ** Maximum`, and `parameter min. Typ. max. ... Units`. These are table-structure words, not amplifier words: Min/Typ/Max is the semiconductor industry's column convention, so this generalizes to mixers, switches and filters.

*Alternative considered.* A positional guard — furniture sits at a consistent y in the page margin, a table header sits in the body — is more principled and needs char coordinates. It is over-engineering for a risk that did not materialise once in five documents: no header came within half the threshold.

### The module yields segments; it does not choose how many model calls happen

`pdf.py` returns an ordered list of budget-sized segments. A caller that wants one focused call takes the first; a caller that wants to chunk-and-merge iterates all of them.

This is deliberate: the single-call-vs-chunked question is genuinely open, and encoding either answer here would force a rewrite when it is settled. Producing segments serves both, and keeps the module's responsibility to *text*.

Segments follow page boundaries — a page is the natural unit (parameters cluster in one table) and it is where the measured win came from. A page is split only if it alone exceeds the budget.

*Dilution re-confirmed.* Same model, same `drain_voltage`: on the dense two-table page 2 it degraded to `{"value":"28 V"}` (a string in the wrong field); on the single focused DC table it returned `{"typ":28}`. The value was present and inside the window in both cases — only the surrounding noise differed. Focused context, not a bigger window, is the fix.

### Relevance scoring is deterministic and model-free

Ordering segments by a model call would make the module non-deterministic, slow, and circular (a model call to decide what to give the model). Scoring is plain text matching of the requested parameter names and their obvious synonyms against segment text, so the same PDF plus the same names always yields the same order — which is what makes the evaluator's gold comparison meaningful.

### Budget is expressed in characters, and is the caller's

The caller knows its model's window; this module does not. It takes a character budget rather than tokens because it cannot tokenize without knowing the model.

Callers must know the conversion is not 4:1, and that there is no single ratio — it depends on the rendering. Measured on CMPA p1: plain ≈2.9, pipe ≈2.6, layout ≈8.2 characters per token (pipe's `|` delimiters are token-dense; layout's padding spaces are token-cheap). The instruction alone costs ~972 tokens of a 2048 window. A character budget is a rendering-independent unit the caller converts against its own model — which is exactly why the budget stays the caller's.

## Risks / Trade-offs

- **The layout-mode fallback inflates text ~3–5x** → on a page that fails the content-preservation guard, columns are recoverable but fewer pages fit a small window. Mitigated two ways: the primary pipe rendering costs only ~18% more tokens than flattened text (×1.04 in characters), so the layout fallback is the exception (12 of 73 pages); and segmentation gives the caller focused text sized to its budget instead of the whole document.
- **`layout=True` also pads *inside* lines** (`GaN  High Power Amplifier`) → exact substring matching against extracted text can miss. Furniture matching therefore compares stripped text; downstream consumers must not assume single spaces.
- **The 80% threshold is a heuristic** → a datasheet that is mostly spec pages could push a header over it. Mitigated by the keyword guard, which makes the failure require two unlikely things at once: an over-threshold header that also avoids every guarded word.
- **Performance-curve pages cannot be detected** → structurally a plot is indistinguishable from a mechanical drawing (measured: plot page 50% image area; the Mechanical page carrying `Die size: 4530 µm x 6090 µm` is 47%), so any area rule deletes the dimensions. Heading keywords reach only 3 of 5 vendors. Left undone rather than done wrong; their titles still cost ~27% of the cleaned text, and their captions (`I_DQ = 650 mA, P_IN = 22 dBm`) are plausible-looking numbers that are plot conditions, not specs.
- **Evaluation-board / BOM sections are a live hallucination trap** → parts lists carry `50V`, `100V`, `0.1uF`, `0 Ohm`, and eval-board markers appear in **5 of 5** vendors. A `Voltage` request could capture a capacitor's rating. Not addressed here because a naive keyword could drop a Features page that merely mentions an evaluation board; deferred until it can be verified rather than guessed.
- **Rotated text extracts as reversed gibberish** (`sreifilpmA`, `rewop`, `)mBd(` in the Hittite datasheet) → these are vertical side-tabs and axis labels. Since they repeat on most pages, de-duplication happens to collapse them to one copy; no targeted handling is proposed.
- **Relevance scoring can rank wrongly** → a parameter stated only in prose, or under vendor-specific wording, may not match its page. The budget is a floor, not a filter: callers that need certainty can iterate all segments, which is exactly the second consumption strategy this design keeps open.

## Open Questions

- **RESOLVED — how a detected table is rendered.** The three-way measurement (layout-aligned vs pipe-table vs key=value) is done: the per-cell **pipe table** wins, with an empty-table filter, sibling-header propagation, and a content-preservation fallback (see Decisions). The headerless-table gap the old note flagged is answered by header propagation.
- **Multi-value Typ cells and the condition column (open).** An AC-spec row states one parameter at several frequencies in a single Typ cell (`47.4 47.9 47.6`) and carries a wide, empty-headed condition column. Both break the small model: values land in `max` instead of `typ`, and only one of the three is captured. Whether pdf.py should zip the value list against the condition's frequencies, render the multi-values as an explicit list, or move the condition out of the pipe row is unresolved and needs its own measurement.
- **Is a page the right segment unit** for a spec table that spans pages? None of the five surveyed do, but a continued table would lose its header in the second segment — related to the header-propagation decision.

## Findings beyond this change's scope (recorded so they are not re-derived)

Driving the module end-to-end surfaced extraction issues that are **not** pdf.py's to fix; they belong to `extractor.py` / the instruction and are noted here only as pointers for a future change:

- **`temperature=0`, `num_ctx`, and determinism are not the problem.** The provider does send `temperature=0`; identical input returns identical output across runs; the CMPA page-2 prompt is 1,539 tokens and `num_ctx=8192` yields a byte-identical result, so there is no silent truncation. Earlier apparent "randomness" was different inputs (different requested-parameter lists), each deterministic on its own.
- **Name mapping is an instruction concern, not ontology.** `ontology/parameters.py` has no synonym field, so it cannot map a request to vendor wording. A request for `VDD` returned `{}` on a datasheet that states `Drain Voltage`; adding one synonym line to the instruction returned `{"typ":28}`. This is the extraction contract's job, not this module's.
- **Absent categorical params hallucinate, and the instruction cannot reliably stop it.** `MSL` extracts correctly where stated (`3`, `1`) but on a datasheet without it the model emits the instruction's own example (`"3"`); abstracting the example and adding an explicit "absent → null" rule both failed (the model then parroted the new placeholder `"1..5"`). The reliable fix is a deterministic code-level grounding check — null a categorical value whose keyword does not appear in the fed text — in `extractor.py`.
- **Physical dimensions live in prose and need a deterministic parser, not the model.** Die/package size is stated as unlabelled prose (`Die size: 4530 µm x 6090 µm`). The model extracts the two numbers but pollutes them — it reads the `(+0/-50 µm)` tolerance as a range and fabricates a max (`length {min:4530, max:4830}`), varies run-to-run, and parrots the instruction's `9.00 x 8.00 mm` example for `size`. The reliable fix is a deterministic code-level dimension parser (regex `A x B unit`) that bypasses the model for this structured pattern. The length/width convention is a product decision, **resolved: the first dimension is length, the second is width** (`4530 µm x 6090 µm` → length=4530, width=6090).
