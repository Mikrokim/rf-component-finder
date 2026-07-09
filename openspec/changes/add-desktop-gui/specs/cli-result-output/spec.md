## MODIFIED Requirements

### Requirement: Grouped result rendering

The CLI SHALL sort verified candidates so that `match` precedes `partial` precedes `fail`, print the per-tier counts, and list the `match` group then the `partial` group, each line showing the model, per-parameter status markers (`✓` for PASS, `✗` for FAIL, `?` for UNKNOWN), and the product URL. The `match` group SHALL list at most `max_results` rows (the configurable cap, default 10, from `config.yaml`); when more matches exist, the CLI SHALL print a note that only the top `max_results` of the total are shown. IF there are no `match` and no `partial` candidates, the CLI SHALL print an explicit "No matching or partial-match components found." message. The CLI SHALL offer to display the failing candidates on demand. Ranking SHALL be by tier only (there is no within-tier margin ordering), and the computed confidence label SHALL NOT be displayed.

#### Scenario: Results grouped by outcome with status markers

- **WHEN** verified candidates include matches and partials
- **THEN** matches are listed before partials, each with per-parameter `✓`/`✗`/`?` markers and a URL

#### Scenario: More than ten matches lists only the top ten

- **WHEN** more than 10 candidates are `match`
- **THEN** the CLI lists 10 match rows and prints a note giving the total and that only the top 10 are shown

#### Scenario: No matches or partials prints an explicit message

- **WHEN** no candidate is `match` or `partial`
- **THEN** the CLI prints "No matching or partial-match components found."
