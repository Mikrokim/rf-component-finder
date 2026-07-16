## MODIFIED Requirements

### Requirement: Extract datasheet text from a PDF

The system SHALL provide `datasheet_text_from_pdf(path, *, pages=None)` which opens a datasheet PDF with `pdfplumber` and returns its page text joined into a single string. `pages=None` SHALL read every page; a list of 0-based page indices SHALL restrict extraction to those pages. Pages that yield no text or whitespace-only text SHALL be skipped, and non-empty pages SHALL be separated by a blank line (`\n\n`). When no page yields extractable text the result SHALL be the empty string. The function SHALL raise `FileNotFoundError` when the path does not exist.

Page text SHALL be read in layout-preserving mode (`extract_text(layout=True)`) so that a specification table's columns stay spatially aligned and the horizontal position of a number continues to identify the column (Min / Typ / Max) it was printed under. Leading whitespace on a line is therefore significant and SHALL be preserved; only trailing whitespace SHALL be stripped.

The joined text SHALL have repeated page furniture emitted once, per the *Repeated page furniture is emitted once* requirement.

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

#### Scenario: Page text is read in layout-preserving mode

- **WHEN** `_join_page_text` reads a page
- **THEN** it requests that page's text with `layout=True`

#### Scenario: Column-aligning leading whitespace survives

- **WHEN** a page yields the layout-aligned line `"    Drain Voltage      V     —      28      —"`
- **THEN** that line appears in the result with its leading spaces intact
- **AND** its trailing spaces are removed

## ADDED Requirements

### Requirement: Repeated page furniture is emitted once

A line that appears on at least 80% of a datasheet's pages is page furniture — a banner, header or footer — and SHALL be emitted only on its FIRST occurrence; later occurrences SHALL be dropped.

Furniture SHALL be de-duplicated, never deleted: across surveyed vendors the banner itself states real parameters (a frequency range in four of five datasheets, plus power ratings), so dropping every occurrence would lose data that appears nowhere else.

A line matching the table-header guard — case-insensitively containing any of `min`, `max`, `typ`, `nom`, `typical`, `minimum`, `maximum`, `nominal`, `parameter`, `unit`/`units`, `symbol`, `condition`/`conditions`, `rating`, `value` — SHALL NEVER be treated as furniture, regardless of how often it repeats. Collapsing a repeated specification-table header would destroy the very column context layout-preserving extraction exists to keep.

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
