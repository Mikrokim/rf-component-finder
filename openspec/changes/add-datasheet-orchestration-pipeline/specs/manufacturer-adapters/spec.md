## ADDED Requirements

### Requirement: Adapters may supply a per-part datasheet URL

An adapter MAY populate `Candidate.datasheet_url` with a direct link to the part's datasheet PDF when the source exposes one. This field is OPTIONAL: an adapter that has no per-part datasheet link SHALL leave `datasheet_url` as `None`, and the candidate SHALL still be valid and usable through Gate 1. The datasheet-orchestration enrichment stage consumes this field; a candidate without it cannot be enriched (its site-missing parameters stay `UNKNOWN`).

#### Scenario: Adapter with a datasheet link populates the field

- **WHEN** a source exposes a per-part datasheet PDF link and the adapter reads it
- **THEN** the emitted `Candidate` carries that link in `datasheet_url`

#### Scenario: Adapter without a datasheet link leaves it None

- **WHEN** a source exposes no per-part datasheet link
- **THEN** the emitted `Candidate` has `datasheet_url` set to `None`
- **AND** the candidate is still returned and evaluated at Gate 1
