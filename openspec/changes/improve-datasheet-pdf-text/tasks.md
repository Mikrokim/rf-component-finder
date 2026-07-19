## 1. Pure table-rendering helpers (no PDF, fake-input tested)

- [ ] 1.1 Add `_render_pipe_table(grid: list[list[str]]) -> str` to `rf_finder/datasheet/pdf.py`: each row as `"| " + " | ".join(cells) + " |"`, an empty cell rendered as `-`. (spec: *Detected tables… → A cell grid renders as pipe rows*)
- [ ] 1.2 Add `_grid_fill_fraction(grid)` and the empty rule: a grid less than 25% filled → dropped; a row with no filled cell → dropped. (spec: *Empty or plot tables are dropped*)
- [ ] 1.3 Add `_content_tokens(text) -> collections.Counter` — technical tokens only (`[0-9A-Za-z…]+`), ignoring `|`/`=` scaffolding; the subset test for the preservation guard. (spec: *Rendering never loses content*)
- [ ] 1.4 Add `_row_has_header(row)` (matches the guard words) and `_synthesize_header(col_xcenters, donor_labels, donor_xcenters)` — assign each column the x-nearest donor label. (spec: *A headerless table borrows its sibling's header*)

## 2. Table detection & per-cell extraction (geometry, PDF-backed)

- [ ] 2.1 Add `_cell_text(page, bbox) -> str` — crop the page to the cell bbox and extract its text, clamped to page bounds.
- [ ] 2.2 Add `_page_tables(page)` producing, per detected `find_tables()` table: its grid (via `_cell_text`), the parallel cell-bbox list, per-column x-centres, `top` y, and a header flag; apply the empty-table/empty-row filter here so a dropped table claims no bboxes. (spec: *Empty or plot tables…* + *Detected tables…*)
- [ ] 2.3 Propagate headers: each headerless table borrows the nearest preceding header table's labels via `_synthesize_header`; none preceding → left unlabelled. (spec: *A headerless table…*)
- [ ] 2.4 Add `_prose_lines(page, claimed_cell_bboxes)` — `extract_words()` minus any word whose centre lies inside a claimed cell bbox, clustered into lines by `top`. (spec: *Detected tables… → text between cells stays in prose*)

## 3. Per-page render with content-preservation fallback

- [ ] 3.1 Add `_render_page(page) -> str`: interleave the prose lines and the rendered pipe tables by `top`, in reading order.
- [ ] 3.2 Guard: if `_content_tokens(page.extract_text())` is NOT a sub-multiset of `_content_tokens(rendered)`, return `page.extract_text(layout=True)` instead (keep leading spaces, strip only trailing). (spec: *Rendering never loses content* + *The fallback preserves column-aligning whitespace*)

## 4. Furniture de-duplication (pure, line-level)

- [ ] 4.1 Add `_HEADER_GUARD` regex (`min|max|typ|nom|typical|minimum|maximum|nominal|parameter|units?|symbol|conditions?|rating|value`, case-insensitive).
- [ ] 4.2 Add `_dedup_furniture(page_texts: list[str]) -> list[str]`: a line on ≥80% of pages (compared by `.strip()`) is furniture → keep its first occurrence, drop the rest; never dedup a `_HEADER_GUARD` line; skip entirely for documents with fewer than 4 pages. (spec: *Repeated page furniture is emitted once*)

## 5. Budget-sized segmentation

- [ ] 5.1 Add `datasheet_segments(path, requested_parameters, *, budget, pages=None) -> list[str]`: build cleaned per-page text (render + dedup), then group pages into segments no larger than `budget` characters, splitting a single page only if it alone exceeds the budget. (spec: *Datasheet text is offered as budget-sized segments*)
- [ ] 5.2 Deterministic, model-free relevance scoring by requested-name text match; empty names → document order; every non-furniture line lands in exactly one segment.

## 6. Wire into datasheet_text_from_pdf

- [ ] 6.1 Keep `_join_page_text(rendered_texts: list[str]) -> str` a PURE string joiner (skip empty/whitespace-only, join with `\n\n`) — testable with fake strings, no PDF. Rewrite `datasheet_text_from_pdf(path, *, pages=None)` to render each selected page via `_render_page` (task 3), run `_dedup_furniture` (task 4), then `_join_page_text`; preserve the signature, the `pages` behaviour, skip-empty, the empty-string result, and `FileNotFoundError`. (spec: *Extract datasheet text from a PDF*)

## 7. Verify

- [ ] 7.1 Unit tests (no PDF) in `tests/test_datasheet_pdf.py`: `_join_page_text` join/skip on fake strings; `_render_pipe_table` grid→pipe; the empty-table/empty-row filter; the `_content_tokens` subset guard; `_synthesize_header` x-alignment; `_dedup_furniture` (banner kept once, banner-borne data survives, guard protects a repeated header, <4-page skip); segmentation (budget respected, deterministic, no-params→document order, every-line-once, oversized page split).
- [ ] 7.2 Integration tests over `evals/pdfs/`: the CMPA keystone — the DC table renders `| Drain Voltage | … | 28 | … |` with 28 under the Typ column; a plot page is dropped (no all-dash rows); no page loses a source token (guard holds) across all 5 datasheets; honest degradation — a page with no detected tables renders as prose (no less text than plain `extract_text`), and an image-only page is skipped.
- [ ] 7.3 Run the full test suite; confirm existing callers/tests are unaffected.
