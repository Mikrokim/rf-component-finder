## MODIFIED Requirements

### Requirement: Extract datasheet text from a PDF

The system SHALL provide `datasheet_text_from_pdf(path, *, pages=None)` which opens a datasheet PDF with `pdfplumber` and returns its page text joined into a single string. `pages=None` SHALL read every page; a list of 0-based page indices SHALL restrict extraction to those pages. Pages that yield no text or whitespace-only text SHALL be skipped, and non-empty pages SHALL be separated by a blank line (`\n\n`). When no page yields extractable text the result SHALL be the empty string. The function SHALL raise `FileNotFoundError` when the path does not exist.

A page's specification tables SHALL be rendered as explicitly-delimited pipe tables, so a number's column (Min / Typ / Max) is marked rather than merely implied by horizontal position: each detected table is rendered `| cell | cell | … |` per row, each cell's text taken from its own bounding box, and the page's remaining prose interleaved around the tables in reading order. This per-page rendering is defined further by the *Detected tables are rendered as pipe tables*, *Empty or plot tables are dropped*, *A headerless table borrows its sibling's header*, and *Rendering never loses content* requirements below.

A page whose pipe rendering would drop any token of its `extract_text()` SHALL instead be rendered in layout-preserving mode (`extract_text(layout=True)`) for that page. In that fallback, leading whitespace is significant and SHALL be preserved; only trailing whitespace SHALL be stripped.

The joined text SHALL have repeated page furniture emitted once, per the *Repeated page furniture is emitted once* requirement.

#### Scenario: Rendered pages are joined with a blank line

- **WHEN** `_join_page_text` is given the rendered page texts `"PAGE ONE"` and `"PAGE TWO"`
- **THEN** the result is `"PAGE ONE\n\nPAGE TWO"`

#### Scenario: Empty and text-less rendered pages are skipped

- **WHEN** the rendered page texts are `"REAL"`, `None`, `"   "`, and `"MORE"`
- **THEN** the result is `"REAL\n\nMORE"` (no blank blocks for the skipped pages)

#### Scenario: No extractable text gives an empty string

- **WHEN** every rendered page text is `None` or `""`
- **THEN** the result is the empty string `""`

#### Scenario: Missing PDF path raises FileNotFoundError

- **WHEN** `datasheet_text_from_pdf` is called with a path that does not exist
- **THEN** it raises `FileNotFoundError`

#### Scenario: A detected spec table is rendered as a pipe table

- **WHEN** a page holds a spec table whose Typ column reads `28` for the `Drain Voltage` row
- **THEN** the rendered page contains that row as pipe-delimited cells `| Drain Voltage | … | 28 | … |`, with `28` under the Typ column
- **AND** the value is not flattened into a position-only line

#### Scenario: The fallback preserves column-aligning whitespace

- **WHEN** a page fails the content-preservation check and falls back to `layout=True`, yielding the aligned line `"    Drain Voltage      V     —      28      —"`
- **THEN** that line appears in the result with its leading spaces intact
- **AND** its trailing spaces are removed

## ADDED Requirements

### Requirement: Detected tables are rendered as pipe tables with per-cell text

The system SHALL detect a page's tables and render each as a pipe table — one `| cell | cell | … |` line per row — with every cell's text taken from that cell's own bounding box, and the page's remaining prose interleaved with the tables in reading order.

A word SHALL be treated as table content, and so removed from the surrounding prose, ONLY when it lies inside an extracted cell's bounding box. A word inside a table's outer rectangle but outside every extracted cell SHALL remain in the prose, so that no source text is both claimed by a table and dropped from its cells.

#### Scenario: A cell grid renders as pipe rows

- **WHEN** the pipe formatter is given the grid `[["Parameter", "Units", "Typ."], ["Drain Voltage", "V", "28"]]`
- **THEN** it returns `"| Parameter | Units | Typ. |\n| Drain Voltage | V | 28 |"`

#### Scenario: Text inside the table rectangle but outside its cells stays in prose

- **WHEN** a page has a word that falls within a detected table's bounding box but within none of its extracted cells
- **THEN** that word still appears in the rendered page as prose, not dropped

### Requirement: Empty or plot tables are dropped, and their cells released to prose

`find_tables()` may mis-detect a plot's gridlines as a table. A detected table whose cells are less than 25% filled SHALL NOT be rendered, and its cell regions SHALL NOT be removed from the prose, so any real text under it remains available. Within a rendered table, a row whose cells are all empty SHALL be dropped. Dropping empty cells and rows SHALL NOT remove content, since an empty cell carries no text.

#### Scenario: A mostly-empty grid is not treated as a table

- **WHEN** a detected table's grid is more than 75% empty cells
- **THEN** it contributes no pipe rows to the rendered page
- **AND** any text within its region remains available as prose

#### Scenario: An all-empty row is dropped from a kept table

- **WHEN** a rendered table contains a row whose every cell is empty
- **THEN** that row does not appear in the output

### Requirement: A headerless table borrows its sibling's header by column position

A detected table with no header row — no row matching the table-header guard words — SHALL be given a synthesized header taken from the nearest preceding table that has one, assigning each headerless column the label of the x-nearest header column. When no preceding header table exists, the table SHALL be rendered without a synthesized header.

#### Scenario: A headerless table receives Min/Typ/Max labels

- **WHEN** a table with data rows like `| Drain Voltage | V | — | 28 | — |` has no header of its own, and the nearest preceding table carries the header `| Parameter | Units | Min. | Typ. | Max. |`
- **THEN** the headerless table is rendered with a header row whose `Min.` / `Typ.` / `Max.` labels sit over its matching columns

#### Scenario: A headerless table with no header sibling is left unlabelled

- **WHEN** a headerless table has no preceding table that carries a header
- **THEN** it is rendered without a synthesized header row

### Requirement: Rendering never loses content

The system SHALL verify, for each page, that every technical token of the page's plain `extract_text()` also appears in that page's rendered output, comparing tokens as a multiset and ignoring the pipe/equals scaffolding characters the renderer adds. A page whose rendering is missing any source token SHALL instead be emitted as its `extract_text(layout=True)` text, which preserves content. The rendered output MAY contain additional tokens (synthesized headers, empty-cell placeholders) — only lost tokens trigger the fallback.

#### Scenario: A page that would lose a token falls back to layout mode

- **WHEN** a page's pipe rendering omits a token that is present in its plain `extract_text()`
- **THEN** that page's contribution to the result is its `layout=True` extraction instead of the pipe rendering

#### Scenario: A fully-preserved page keeps its pipe rendering

- **WHEN** a page's pipe rendering contains every token of its plain `extract_text()`
- **THEN** that page's contribution to the result is the pipe rendering

### Requirement: Repeated page furniture is emitted once

A line that appears on at least 80% of a datasheet's pages is page furniture — a banner, header or footer — and SHALL be emitted only on its FIRST occurrence; later occurrences SHALL be dropped.

Furniture SHALL be de-duplicated, never deleted: across surveyed vendors the banner itself states real parameters (a frequency range in four of five datasheets, plus power ratings), so dropping every occurrence would lose data that appears nowhere else.

A line matching the table-header guard — case-insensitively containing any of `min`, `max`, `typ`, `nom`, `typical`, `minimum`, `maximum`, `nominal`, `parameter`, `unit`/`units`, `symbol`, `condition`/`conditions`, `rating`, `value` — SHALL NEVER be treated as furniture, regardless of how often it repeats. Collapsing a repeated specification-table header would destroy the very column context the pipe rendering exists to mark.

De-duplication SHALL be skipped entirely for documents with fewer than 4 pages, where "repeats on most pages" carries no signal. Lines SHALL be compared by their stripped text, so layout padding does not defeat the match.

#### Scenario: A repeated banner is kept once

- **WHEN** four pages each begin with the line `"ACME Corp - all rights reserved"`
- **THEN** that line appears exactly once in the joined result

#### Scenario: Banner-borne data survives de-duplication

- **WHEN** five pages each carry the banner line `"75 Ohm 45 to 1218 MHz"`
- **THEN** `"75 Ohm 45 to 1218 MHz"` still appears in the result (once), not zero times

#### Scenario: A repeated table header is protected by the guard

- **WHEN** every page of a five-page datasheet carries the line `"Parameter Symbol Min. Typ. Max. Unit"`
- **THEN** that line is NOT treated as furniture
- **AND** it appears on every page of the result

#### Scenario: A line appearing on only some pages is not furniture

- **WHEN** a line appears on 2 of 10 pages
- **THEN** it is below the 80% threshold and every occurrence is kept

#### Scenario: Short documents are not de-duplicated

- **WHEN** a 3-page document repeats a line on all 3 pages
- **THEN** de-duplication does not apply and all 3 occurrences are kept

### Requirement: Datasheet text is offered as budget-sized segments

The system SHALL provide an entry point that returns the datasheet's cleaned text as an ordered list of *segments*, each no larger than a caller-supplied size budget, ordered by relevance to a caller-supplied list of requested parameter names.

Segmenting exists because whole-document text measurably degrades extraction even when it fits the model's context window: given the full document the extractor returned nulls and mis-filed fields, while the same model given only the relevant page returned the correct values. Segments let a caller supply focused context.

Relevance scoring SHALL be deterministic and SHALL NOT invoke a model, so the same PDF and parameter names always yield the same ordering. When no parameter names are supplied, segments SHALL be returned in document order.

Segmentation SHALL NOT lose content: every non-furniture line of the source SHALL appear in exactly one segment. A segment SHALL NOT split a page's text across two segments unless that single page alone exceeds the budget.

This requirement defines only how segments are produced and ordered. Whether a caller extracts from one segment or from every segment, and how multiple results are merged, is outside this capability.

#### Scenario: Segments respect the budget

- **WHEN** segmentation runs with a budget of 1000 characters
- **THEN** no returned segment exceeds 1000 characters

#### Scenario: Segments are ordered by relevance to the requested parameters

- **WHEN** the requested parameters are `["length", "width"]` and one page states die dimensions while others do not
- **THEN** the segment containing the dimensions page is ordered before the others

#### Scenario: Scoring is deterministic

- **WHEN** segmentation runs twice with the same PDF and the same requested parameters
- **THEN** both runs return identical segments in an identical order

#### Scenario: No parameters means document order

- **WHEN** segmentation runs with an empty list of requested parameters
- **THEN** the segments are returned in document order

#### Scenario: Every line lands in exactly one segment

- **WHEN** segmentation runs over a multi-page datasheet
- **THEN** concatenating the segments in document order reproduces every non-furniture line of the cleaned text, with none duplicated and none dropped

#### Scenario: An oversized single page is still returned

- **WHEN** one page's text alone exceeds the budget
- **THEN** that page is split across segments rather than dropped
