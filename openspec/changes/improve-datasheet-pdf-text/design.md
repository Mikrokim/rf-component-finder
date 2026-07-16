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

### Use `pdfplumber` layout mode, not a new library

`extract_text(layout=True)` re-inserts whitespace so columns stay aligned, and it keeps prose and tables together in reading order.

*Alternatives considered.* `extract_tables()` alone returns a perfect cell grid but **drops all prose** — on page 0 of CMPA it loses the Features bullet `IM3: <-25 dBc at 44 dBm Pout` and the whole Description, both of which state real values. `pymupdf4llm` is purpose-built for PDF→Markdown-for-LLM and would replace most of this module, but it is **AGPL-3.0**: distributing the product or offering it as a network service would trigger source-disclosure obligations. That is a business decision, not a technical one, and the free path already recovers the measured benefit — so it is rejected for this change and can be revisited if a gap remains.

### De-duplicate furniture; never delete it

A line on ≥80% of pages is furniture. We keep its **first** occurrence.

The naive rule — drop every occurrence — was rejected on evidence: the banner states the frequency range in **four of the five** datasheets (`75Ω 45 to 1218 MHz`, `13.75 - 15.5 GHz`, `8 to 12 GHz Useable`, `8 - 14 GHz`) and power ratings (`60 W`, `2 Watt`). Deleting it would silently destroy parameters available nowhere else. Keeping one copy costs ~3% and saves ~42%.

The 80% threshold, and the ≥4-page floor below which de-duplication is skipped, are judgement calls: on the surveyed set every real furniture line sits at 89–100% and the nearest non-furniture line is at 44%, so the gap is wide and the exact cut is not delicate.

### Guard table headers with a narrow keyword list, not geometry

A repeated spec-table header must never be collapsed — that would destroy the very column context layout mode exists to preserve. Any line matching `min|max|typ|nom|typical|minimum|maximum|nominal|parameter|units?|symbol|conditions?|rating|value` is exempt from de-duplication.

*Verified on all five vendors:* the guard matches **none** of the 33 real furniture lines (so it costs no savings) and **every** real table header (so it protects all of them) — including headers phrased `Parameter Symbol Min Typ Max Unit Test Conditions/Comments`, `Parameters Minimum Typical ** Maximum`, and `parameter min. Typ. max. ... Units`. These are table-structure words, not amplifier words: Min/Typ/Max is the semiconductor industry's column convention, so this generalizes to mixers, switches and filters.

*Alternative considered.* A positional guard — furniture sits at a consistent y in the page margin, a table header sits in the body — is more principled and needs char coordinates. It is over-engineering for a risk that did not materialise once in five documents: no header came within half the threshold.

### The module yields segments; it does not choose how many model calls happen

`pdf.py` returns an ordered list of budget-sized segments. A caller that wants one focused call takes the first; a caller that wants to chunk-and-merge iterates all of them.

This is deliberate: the single-call-vs-chunked question is genuinely open, and encoding either answer here would force a rewrite when it is settled. Producing segments serves both, and keeps the module's responsibility to *text*.

Segments follow page boundaries — a page is the natural unit (parameters cluster in one table) and it is where the measured win came from. A page is split only if it alone exceeds the budget.

### Relevance scoring is deterministic and model-free

Ordering segments by a model call would make the module non-deterministic, slow, and circular (a model call to decide what to give the model). Scoring is plain text matching of the requested parameter names and their obvious synonyms against segment text, so the same PDF plus the same names always yields the same order — which is what makes the evaluator's gold comparison meaningful.

### Budget is expressed in characters, and is the caller's

The caller knows its model's window; this module does not. It takes a character budget rather than tokens because it cannot tokenize without knowing the model.

Callers must know the conversion is not 4:1. Measured on this dense technical text, `layout=True` output runs about **1.5 characters per token** — a page that was 1,210 chars becomes 3,539 chars of aligned text, and the instruction alone costs 972 tokens of a 2048 window. Layout mode buys column fidelity and pays in size.

## Risks / Trade-offs

- **Layout mode inflates the text ~3x** → columns are recoverable but fewer pages fit a small window. Mitigated by segmentation: the caller gets focused text sized to its budget instead of the whole document. This trade is the point of the change, not a side effect.
- **`layout=True` also pads *inside* lines** (`GaN  High Power Amplifier`) → exact substring matching against extracted text can miss. Furniture matching therefore compares stripped text; downstream consumers must not assume single spaces.
- **The 80% threshold is a heuristic** → a datasheet that is mostly spec pages could push a header over it. Mitigated by the keyword guard, which makes the failure require two unlikely things at once: an over-threshold header that also avoids every guarded word.
- **Performance-curve pages cannot be detected** → structurally a plot is indistinguishable from a mechanical drawing (measured: plot page 50% image area; the Mechanical page carrying `Die size: 4530 µm x 6090 µm` is 47%), so any area rule deletes the dimensions. Heading keywords reach only 3 of 5 vendors. Left undone rather than done wrong; their titles still cost ~27% of the cleaned text, and their captions (`I_DQ = 650 mA, P_IN = 22 dBm`) are plausible-looking numbers that are plot conditions, not specs.
- **Evaluation-board / BOM sections are a live hallucination trap** → parts lists carry `50V`, `100V`, `0.1uF`, `0 Ohm`, and eval-board markers appear in **5 of 5** vendors. A `Voltage` request could capture a capacitor's rating. Not addressed here because a naive keyword could drop a Features page that merely mentions an evaluation board; deferred until it can be verified rather than guessed.
- **Rotated text extracts as reversed gibberish** (`sreifilpmA`, `rewop`, `)mBd(` in the Hittite datasheet) → these are vertical side-tabs and axis labels. Since they repeat on most pages, de-duplication happens to collapse them to one copy; no targeted handling is proposed.
- **Relevance scoring can rank wrongly** → a parameter stated only in prose, or under vendor-specific wording, may not match its page. The budget is a floor, not a filter: callers that need certainty can iterate all segments, which is exactly the second consumption strategy this design keeps open.

## Open Questions

- **How should a detected table be rendered?** Layout mode is proven to fix field placement, but it still asks the model to infer a column from horizontal position. An explicitly labelled rendering — `Drain Voltage: unit=V, min=-, typ=28, max=-` — would remove that inference entirely, which should matter most for exactly the weak small models this design targets. A three-way measurement (aligned vs pipe-table vs explicit key=value) is in flight; the specs must record the rendering that measurement selects, not the one that sounds best. Note that `extract_tables()` did **not** parse a header row for the DC table on page 1, so an explicit rendering needs an answer for headerless tables.
- **Should segment relevance consider the ontology's synonyms** (`rf_finder/ontology/`) rather than only the literal requested names? It would improve matching for vendor-specific wording, at the cost of coupling this module to the ontology.
- **Is a page the right segment unit for datasheets whose spec table spans pages?** None of the five surveyed do, but a table continued across a page break would lose its header in the second segment.
