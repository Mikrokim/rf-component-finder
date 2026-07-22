## ADDED Requirements

### Requirement: Adapters supply a per-part datasheet URL

An adapter SHALL populate `Candidate.datasheet_url` with a link to the part's datasheet PDF whenever the source publishes one for that part. A source publishes that link in one of exactly three ways, and the adapter SHALL handle whichever applies to its site:

1. **On the page the adapter already scrapes** — the results table/row, or the payload it already fetches. The adapter reads the link during `search()` and the emitted `Candidate` carries it immediately, at no extra request cost.
2. **Only on a per-part product page** — the link cannot be read during `search()` without one extra fetch per listed part. The adapter SHALL leave `datasheet_url` as `None` during `search()` and resolve it **on demand** instead (see "Adapters resolve a product-page-only datasheet link on demand").
3. **Nowhere** — the source publishes no per-part datasheet link at all.

`datasheet_url` SHALL be `None` after `search()` in cases 2 and 3, and SHALL remain `None` after resolution ONLY in case 3. A candidate whose `datasheet_url` is `None` SHALL still be valid and usable through Gate 1.

Case 2 SHALL NOT be treated as case 3: a source that publishes the link on a product page **does** have a datasheet link, and reporting it as "no link" would silently deny the part a datasheet it actually has.

#### Scenario: A link on the already-scraped page is read during search

- **WHEN** a source exposes a per-part datasheet PDF link on the page the adapter already scrapes
- **THEN** the emitted `Candidate` carries that link in `datasheet_url`
- **AND** no additional request is made to obtain it

#### Scenario: A product-page-only link is deferred, not discarded

- **WHEN** a source exposes the datasheet link only on a per-part product page
- **THEN** `search()` emits the `Candidate` with `datasheet_url` as `None` and does NOT fetch the product page
- **AND** the adapter is still able to resolve that link on demand for a given candidate

#### Scenario: A source with no datasheet link at all

- **WHEN** a source publishes no per-part datasheet link anywhere
- **THEN** the emitted `Candidate` has `datasheet_url` set to `None`
- **AND** the candidate is still returned and evaluated at Gate 1

### Requirement: Adapters resolve a product-page-only datasheet link on demand

An adapter SHALL expose an operation that resolves the datasheet URL for ONE given candidate (e.g. `resolve_datasheet_url(candidate) -> str | None`), which the management layer calls for selected candidates only. This is the seam that lets a case-2 source contribute a datasheet link without paying a per-part fetch during retrieval.

The DEFAULT behavior SHALL be to return the `datasheet_url` the candidate already carries, so every adapter that reads the link inline (case 1) or has no link at all (case 3) satisfies this requirement with no site-specific work. Only a case-2 adapter overrides it, and the site-specific knowledge of how to reach the product page and read the link out of it SHALL live in that adapter — not in the management layer, which SHALL NOT contain per-site link-discovery logic.

`search()` SHALL NOT fetch per-part product pages: retrieval returns every part the source lists for the component type, so resolving there would cost one request per listed part regardless of how few candidates survive Gate 1.

The operation SHALL return `None` rather than raise when the link cannot be resolved — the product page fails to fetch, or it exposes no datasheet link. A resolution failure therefore collapses into the existing "no datasheet link" condition rather than introducing a new failure mode.

Resolution SHALL respect the source's `robots.txt`: an adapter SHALL NOT fetch a product-page URL that robots disallows, even when the results table links to it. Where a disallowed URL and an allowed one address the same product page, the adapter SHALL use the allowed one.

#### Scenario: The default returns the link the candidate already carries

- **WHEN** the management layer resolves the datasheet URL for a candidate from an adapter that reads the link inline
- **THEN** the candidate's existing `datasheet_url` is returned unchanged
- **AND** no request is made

#### Scenario: A case-2 adapter resolves the link from the product page

- **WHEN** the management layer resolves the datasheet URL for a candidate whose source publishes the link only on a product page
- **THEN** the adapter fetches that candidate's product page and returns the datasheet link found on it

#### Scenario: An unresolvable link yields None, not an error

- **WHEN** resolution is attempted and the product page cannot be fetched, or it carries no datasheet link
- **THEN** the operation returns `None` and does not raise
- **AND** the candidate is treated as having no datasheet link

#### Scenario: Resolution never fetches a robots-disallowed URL

- **WHEN** a source's results table links to a product page at a URL that `robots.txt` disallows
- **THEN** the adapter does not fetch that URL
- **AND** it either uses an allowed URL for the same product page or resolves to `None`

### Requirement: A supplied datasheet URL is absolute and fetchable

When an adapter supplies a `datasheet_url` — whether read inline or resolved on demand — that value SHALL be an absolute URL that can be fetched as-is. Sources commonly publish the link as a relative `href` (e.g. `/pdfs/PART.pdf`); the adapter SHALL resolve such an `href` against the source's base URL before setting the field.

The field's only consumer is the datasheet fetch stage, which passes it straight to `datasheet_text_from_url` and fetches it as given; a relative value would fail there.

#### Scenario: A relative datasheet href is made absolute

- **WHEN** a source publishes the datasheet link as a relative `href`
- **THEN** the adapter resolves it against the source's base URL
- **AND** the emitted `datasheet_url` is an absolute URL

#### Scenario: The supplied URL is directly fetchable

- **WHEN** a candidate carries a non-`None` `datasheet_url`
- **THEN** that value can be passed to the datasheet fetch stage without further rewriting
