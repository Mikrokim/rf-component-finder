## ADDED Requirements

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

The components returned by the Skill SHALL be shown in the **same results table** the deterministic Search populates — the same `Treeview` and columns (model, manufacturer, verdicts, url) — not in a dialog or a separate window. Rendering SHALL replace the table's current contents (as a new search does) and map each returned component to a row. Double-clicking a row SHALL open its url, consistent with Search. WHEN the Skill returns no components, the window SHALL show an explicit "no components" indication rather than an empty table with no explanation. The existing `_deliver_results` rendering used by deterministic Search SHALL remain unchanged; AI Search SHALL use its own rendering path into the shared table.

#### Scenario: Returned components fill the results table

- **WHEN** an AI Search returns a list of components
- **THEN** the results table is cleared and shows one row per returned component, with its model, manufacturer, verdict, and url
- **AND** double-clicking a row opens that component's url

#### Scenario: Empty result is shown explicitly

- **WHEN** an AI Search returns no components
- **THEN** the window shows an explicit "no components" indication and an empty table

### Requirement: Skill failure is reported without crashing

IF an AI Search fails — for example the Claude Agent SDK is not installed, the run is not authenticated, the run errors, or the returned data cannot be read as a component list — the window SHALL surface the error in a dialog, re-enable the AI Search button, and SHALL NOT close or crash. The deterministic Search action SHALL remain usable regardless of AI-Search failures.

#### Scenario: Missing SDK or unauthenticated run surfaces as an error

- **WHEN** an AI Search raises because the SDK is unavailable or the run cannot authenticate
- **THEN** the window shows the error in a dialog and re-enables the AI Search button
- **AND** the window stays open and Search still works

#### Scenario: Unreadable result surfaces as an error

- **WHEN** the Skill returns data that cannot be interpreted as a list of components
- **THEN** the window shows an error in a dialog rather than crashing, and the results table is left in a valid state
