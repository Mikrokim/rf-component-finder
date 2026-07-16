# Desktop GUI Specification

## Purpose

Define the Tkinter desktop application that offers an additive, alternative entry point to the terminal CLI. The GUI renders an ontology-driven form for the selected component type, delegates constraint parsing to the existing `collect` seam, runs searches off the UI thread, and presents matching components in a table with browser deep-links.

## Requirements

### Requirement: Desktop window entry point

The system SHALL provide a Tkinter desktop application launchable with `python -m rf_finder.ui.gui`. Launching it SHALL open a single window titled for the tool, with the component-type selector and an empty results area. Adapters fetch live on each search (the same way the CLI does). The existing `python -m rf_finder` CLI SHALL remain available; the GUI is an additive, alternative entry point.

#### Scenario: Window launches

- **WHEN** the user runs `python -m rf_finder.ui.gui`
- **THEN** a single application window opens with the component-type selector and an empty results area

#### Scenario: CLI is unaffected

- **WHEN** the GUI module is added
- **THEN** `python -m rf_finder` still runs the existing interactive terminal flow with no behavioral change

### Requirement: Ontology-driven form rendered from the selected component type

The window SHALL present a component-type selector populated from the ontology `COMPONENTS`, defaulting to `amplifier`. For the selected type the window SHALL render one input group per field returned by `build_form(component_type)`, preserving that function's field order. A range field (`comparison` in `contains` / `between` / `min` / `max`) SHALL render a min entry and a max entry; a scalar field (`eq`) SHALL render a single value entry. Every field SHALL render a unit selector offering `field.units` with the canonical unit (`field.units[0]`) selected by default. Changing the selected component type SHALL rebuild the form to the new type's fields, discarding the previous type's entries.

#### Scenario: Amplifier form is rendered from build_form

- **WHEN** the component type is `amplifier`
- **THEN** the form shows one input group per field of `build_form("amplifier")`, in the same order
- **AND** each range field shows a min and a max entry, each scalar field shows one value entry, and each field shows a unit selector defaulting to its canonical unit

#### Scenario: Changing component type rebuilds the form

- **WHEN** the user selects a different component type in the selector
- **THEN** the form is rebuilt from `build_form(<new type>)` and the previous type's entered values are cleared

#### Scenario: Only ontology types are offered

- **WHEN** the component-type selector is populated
- **THEN** its choices are exactly the keys of the ontology `COMPONENTS`

### Requirement: Form values collected through the existing answers seam

On search, the window SHALL read the entered widgets into an `answers` dict using the established key convention — `"<name>.min"`, `"<name>.max"`, `"<name>.unit"` for range fields and `"<name>.value"`, `"<name>.unit"` for scalar fields — and obtain the `QuerySpec` by calling `collect(schema, answers=answers)`. Empty entries SHALL be omitted (or left empty) so that, per the existing `collect` contract, they produce no constraint. The GUI SHALL NOT reimplement constraint parsing, unit validation, or range logic; it SHALL delegate all of it to `collect`.

#### Scenario: Filled fields become a QuerySpec via collect

- **WHEN** the user enters `freq_range` min `2`, max `6`, unit `GHz` and `P1dB` min `26`, unit `dBm`, and clicks Search
- **THEN** the window builds `answers` with keys `freq_range.min=2`, `freq_range.max=6`, `freq_range.unit=GHz`, `P1dB.min=26`, `P1dB.unit=dBm`
- **AND** the `QuerySpec` used for the search is the result of `collect(schema, answers=answers)`

#### Scenario: Empty fields yield no constraints

- **WHEN** the user clicks Search without entering any field
- **THEN** `collect` is called with no filled keys and the resulting `QuerySpec` has an empty `constraints` list

### Requirement: Search runs without freezing the window

The window SHALL execute the search (each supporting adapter's `search(spec)` followed by `verify(spec, candidate)` for every candidate) on a background thread so the UI thread never blocks during the multi-second fetch. While a search is in progress the window SHALL show a loading indication and SHALL prevent a second concurrent search from being started. Results SHALL be applied to the table on the UI thread once the background work completes.

#### Scenario: UI stays responsive during a search

- **WHEN** the user clicks Search and adapters are being fetched
- **THEN** the window remains responsive and shows a loading state
- **AND** the Search action cannot be triggered again until the in-progress search finishes

#### Scenario: Adapter selection matches the CLI

- **WHEN** a search runs for a component type
- **THEN** only adapters whose `supported_components` include that type are queried, as in the CLI flow
- **AND** each candidate is passed through `verify(spec, candidate)` to obtain its verdict

### Requirement: Matching components shown in a table with browser deep-links

The table SHALL display only the components whose overall verdict is `match`; `partial` and `fail` candidates SHALL be screened out of the table. It SHALL show at most `max_results` (a configurable cap, default 10, loaded from `config.yaml`) matches; when more exist, the window SHALL indicate that only the top `max_results` of the total are shown so the user knows to narrow the filters. The table SHALL have columns model, manufacturer, verdicts, and url. Double-clicking a row SHALL open that candidate's url in the system web browser. When a search yields no `match` candidates, the window SHALL display an explicit "no matching components" indication (including the number screened) rather than an empty table with no explanation.

#### Scenario: Only matches are listed; the rest are screened out

- **WHEN** a search yields a mix of match, partial, and fail candidates
- **THEN** the table lists only the `match` candidates (at most 10)

#### Scenario: More than ten matches shows only the top ten

- **WHEN** a search yields more than 10 `match` candidates
- **THEN** the table shows exactly 10 rows
- **AND** the window indicates the total number of matches and that only the top 10 are shown

#### Scenario: Row opens the datasheet url

- **WHEN** the user double-clicks a result row
- **THEN** that candidate's url is opened in the system web browser

#### Scenario: No matching components found

- **WHEN** a search returns candidates but none with overall verdict `match`
- **THEN** the window shows an explicit "no matching components" indication with the number screened

### Requirement: Numeric fields reject non-numeric input as it is typed

Every value entry (min, max, and scalar value) SHALL accept only characters that form a number in progress (digits, an optional leading `-`, and a single `.`); a keystroke that would make the field non-numeric SHALL be rejected so it never appears. Unit selectors are fixed dropdowns and cannot take a free-typed value.

#### Scenario: Letters cannot be typed into a value field

- **WHEN** the user types a letter into a min/max/value entry
- **THEN** the keystroke is rejected and the field keeps only numeric text

### Requirement: A `contains` field requires both bounds before searching

Because a `contains` parameter (e.g. frequency range) describes a band, a one-sided entry is meaningless. Before searching, IF a `contains` field has exactly one of its min/max filled, the window SHALL report an error naming that field and SHALL NOT run the search — rather than silently dropping the half-entered constraint. A `between`/`min`/`max` field MAY be left one-sided (an open-ended bound) and SHALL NOT trigger this error.

#### Scenario: Half-filled contains range is rejected

- **WHEN** the user fills only the minimum of a `contains` field (e.g. frequency range) and clicks Search
- **THEN** the window shows an error naming that field and does not run the search

#### Scenario: One-sided between range is allowed

- **WHEN** the user fills only the minimum of a `between` field (e.g. gain) and clicks Search
- **THEN** no validation error is raised for that field and the search runs

### Requirement: Invalid input is reported without crashing

When `collect` raises `ValueError` (for example a min greater than max), the window SHALL catch it and present the message in a dialog, leaving the form intact for correction, and SHALL NOT close or crash.

#### Scenario: Bad input surfaces as a dialog

- **WHEN** the user enters a min greater than the max and clicks Search
- **THEN** the `ValueError` from `collect` is caught and its message is shown in a dialog
- **AND** the window stays open with the entered values preserved for correction

### Requirement: AI Search action shares the form with the deterministic Search

The window SHALL provide a second search button, "AI Search", alongside Search. It SHALL take its input from the **same form** the deterministic Search uses — there is no separate input for it. On activation it SHALL build the `answers` dict and call `collect(schema, answers=answers)` exactly as Search does, apply the same pre-search validation, and render the resulting `QuerySpec` constraints into a text summary passed to the Skill. The two buttons differ only in the engine that produces results (deterministic adapters vs. a Claude Skill), never in how the query is entered.

#### Scenario: Both buttons read the same entered parameters

- **WHEN** the user fills the form fields and clicks AI Search
- **THEN** the window builds the `answers` dict and obtains the `QuerySpec` via `collect(schema, answers=answers)`, exactly as clicking Search would
- **AND** no additional, AI-Search-only input is required from the user

#### Scenario: Invalid input is reported without running the Skill

- **WHEN** the entered form fails validation or `collect` raises `ValueError`
- **THEN** the window shows the error in a dialog and does not start the Skill run

### Requirement: AI Search runs the Skill and requests structured component results

AI Search SHALL run whichever Skill the app is currently configured to invoke, via the agent-skill integration, requesting a structured result (an `output_format` schema describing a list of components with at least model, manufacturer, url, and a verdict/note field). It SHALL NOT contain skill-specific logic beyond naming the Skill and the result schema, so the Skill can be swapped without changing this action.

#### Scenario: Skill is invoked with a component-list schema

- **WHEN** AI Search runs
- **THEN** the skill runner is called with the configured skill name and an `output_format` schema for a list of components
- **AND** the parameter summary built from the form is passed as the prompt

### Requirement: Skill run does not freeze the window

The Skill call SHALL execute on a background thread so the UI thread never blocks during the multi-second SDK call. The worker thread SHALL NOT touch any Tk widget directly; the run's outcome (the returned components, or an error) SHALL be handed back to the UI thread through the window's existing result-queue/poll mechanism, using distinct message kinds so the deterministic Search flow is unaffected. While an AI Search is in progress the window SHALL prevent a second concurrent AI Search from being started.

#### Scenario: UI stays responsive during an AI Search

- **WHEN** the user clicks AI Search and the SDK call is in progress
- **THEN** the window remains responsive
- **AND** AI Search cannot be triggered again until the in-progress run finishes

#### Scenario: Outcome reaches the UI only via the queue

- **WHEN** the background worker finishes (with components or an error)
- **THEN** it enqueues the outcome for the UI thread to render and never updates a Tk widget from the worker thread

### Requirement: Skill components rendered into the same results table

The components returned by the Skill SHALL be shown in the **same results table** the deterministic Search populates — the same `Treeview`, not a dialog or a separate window. The table SHALL carry a leading **Source** column, in addition to model, manufacturer, verdicts, and url, marking each row's origin (deterministic Search vs. AI Search). AI Search SHALL **append** its components to the table's current contents — it SHALL NOT clear the table — so results from Search and AI Search combine in one table; only the deterministic Search clears and re-renders the table. Each returned component SHALL map to one appended row tagged as AI-sourced, and double-clicking a row SHALL open its url, consistent with Search. WHEN the Skill returns no components, the window SHALL leave any existing rows untouched and indicate that no components were added, rather than clearing the table. The existing `_deliver_results` rendering used by deterministic Search SHALL remain unchanged apart from also emitting the Source cell; AI Search SHALL use its own append path into the shared table.

#### Scenario: Returned components are appended, combining with existing rows

- **WHEN** the table already shows deterministic Search rows and an AI Search returns a list of components
- **THEN** the AI components are added as new rows without removing the existing rows, each marked as AI in the Source column
- **AND** double-clicking an AI row opens that component's url

#### Scenario: Only Search clears the table

- **WHEN** the deterministic Search runs while AI Search rows are present
- **THEN** the table is cleared and re-rendered from the Search results, removing the AI rows

#### Scenario: Empty AI Search preserves existing rows

- **WHEN** an AI Search returns no components
- **THEN** any existing rows remain in the table and the window indicates that no components were added

### Requirement: Skill failure is reported without crashing

IF an AI Search fails — for example the Claude Agent SDK is not installed, the run is not authenticated, the run errors, or the returned data cannot be read as a component list — the window SHALL surface the error in a dialog, re-enable the AI Search button, and SHALL NOT close or crash. The deterministic Search action SHALL remain usable regardless of AI-Search failures.

#### Scenario: Missing SDK or unauthenticated run surfaces as an error

- **WHEN** an AI Search raises because the SDK is unavailable or the run cannot authenticate
- **THEN** the window shows the error in a dialog and re-enables the AI Search button
- **AND** the window stays open and Search still works

#### Scenario: Unreadable result surfaces as an error

- **WHEN** the Skill returns data that cannot be interpreted as a list of components
- **THEN** the window shows an error in a dialog rather than crashing, and the results table is left in a valid state
