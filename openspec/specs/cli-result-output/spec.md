# CLI Result Output Specification

## Purpose

Define the command-line run flow that ties the form, adapters, and verifier together and renders results to the terminal. This spec documents the behavior **as currently implemented** in `rf_finder/__main__.py`. Note: the dedicated `reporter.py` module is not implemented; all rendering is currently done inline in `__main__`.

## Requirements

### Requirement: Interactive run flow

Running `python -m rf_finder` SHALL execute the pipeline in order: prompt for a component type, build the form, collect constraints interactively, echo the search parameters, dispatch to the registered adapters, verify each returned candidate, and render the grouped results.

#### Scenario: Pipeline executes end to end

- **WHEN** `python -m rf_finder` is run and the form is completed
- **THEN** the tool collects a `QuerySpec`, fetches candidates, verifies them, and prints grouped results

### Requirement: Component type entered as free text

The CLI SHALL read the component type as free-text input defaulting to `amplifier` when the input is empty. IF `build_form` rejects the entered type, the CLI SHALL print an error message and exit without searching.

#### Scenario: Empty input defaults to amplifier

- **WHEN** the user presses Enter at the component-type prompt without typing
- **THEN** the component type used is `amplifier`

#### Scenario: Unknown component type aborts the run

- **WHEN** the user enters a component type not registered in the ontology
- **THEN** the CLI prints an error and returns without fetching candidates

### Requirement: Search-parameter echo before searching

Before searching, the CLI SHALL print a summary of each collected constraint. An open `between` range SHALL render as `any` (both sides open), `≥ <min>` (open top), or `≤ <max>` (open bottom); a bounded range SHALL render as `<low>–<high>`; a scalar SHALL render as `<value> <unit>  [<comparison>]`. IF there are no constraints, the CLI SHALL print a notice that all results will be returned.

#### Scenario: Open and bounded ranges render distinctly

- **WHEN** a `P1dB between (26.0, inf)` constraint is echoed
- **THEN** its range renders as `≥ 26.0`
- **AND WHEN** the range is `(-inf, 30.0)` it renders as `≤ 30.0`
- **AND WHEN** the range is `(2.0, 6.0)` it renders as `2.0–6.0`

#### Scenario: No constraints prints a no-filters notice

- **WHEN** the collected `QuerySpec` has no constraints
- **THEN** the CLI prints a "no filters — returning all results" notice

### Requirement: Adapter dispatch with per-adapter error isolation

The CLI SHALL iterate the registered adapters and query only those whose `supported_components` includes the requested component type. A failure raised by a single adapter's `search` SHALL be caught and reported as a marked line, and the run SHALL continue with the remaining adapters. IF no candidates are returned at all, the CLI SHALL print a "No candidates returned." message and stop.

#### Scenario: One adapter failure does not abort the run

- **WHEN** an adapter's `search` raises an exception
- **THEN** the CLI prints a marked error line for that adapter and continues with the others

#### Scenario: No candidates ends the run cleanly

- **WHEN** no adapter returns any candidate
- **THEN** the CLI prints "No candidates returned." and stops

### Requirement: Grouped result rendering

The CLI SHALL sort verified candidates so that `match` precedes `partial` precedes `fail`, print the per-tier counts, and list the `match` group then the `partial` group, each line showing the model, per-parameter status markers (`✓` for PASS, `✗` for FAIL, `?` for UNKNOWN), and the product URL. IF there are no `match` and no `partial` candidates, the CLI SHALL print an explicit "No matching or partial-match components found." message. The CLI SHALL offer to display the failing candidates on demand. Ranking SHALL be by tier only (there is no within-tier margin ordering), and the computed confidence label SHALL NOT be displayed.

#### Scenario: Results grouped by outcome with status markers

- **WHEN** verified candidates include matches and partials
- **THEN** matches are listed before partials, each with per-parameter `✓`/`✗`/`?` markers and a URL

#### Scenario: No matches or partials prints an explicit message

- **WHEN** no candidate is `match` or `partial`
- **THEN** the CLI prints "No matching or partial-match components found."

### Requirement: Verification is not error-isolated (current limitation)

The CLI SHALL verify each candidate without catching verification errors. Because the `between` comparison currently raises `NameError` (see the Result Verification spec), entering any `between` constraint (`P1dB`, `Gain`, `NF`, or `OIP3`) SHALL cause the run to crash during verification after candidates are fetched. This documents actual current behavior; resilient handling is deferred to a future change.

#### Scenario: A between constraint crashes the run during verification

- **WHEN** the user enters a `P1dB` (or `Gain`/`NF`/`OIP3`) constraint and candidates are fetched
- **THEN** the run raises `NameError` during the verification step
