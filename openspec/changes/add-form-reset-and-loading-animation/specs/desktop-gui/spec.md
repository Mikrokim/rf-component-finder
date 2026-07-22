## ADDED Requirements

### Requirement: One-click form reset

The window SHALL provide a Reset control in the controls row that, when activated, clears every rendered form field of the current component type — emptying each value entry (scalar value, and range min/max) and restoring each field's unit selector to its canonical unit (`field.units[0]`). Reset SHALL NOT change the selected component type and SHALL NOT rebuild the fields. Reset SHALL operate on the existing `field_widgets` records and SHALL be disabled whenever a Search or AI Search is in progress, re-enabling when it completes.

#### Scenario: Reset clears entered values

- **WHEN** the user has entered values into one or more fields and clicks Reset
- **THEN** every scalar value entry and every range min/max entry is emptied
- **AND** every unit selector returns to its canonical unit (`field.units[0]`)

#### Scenario: Reset preserves the component type

- **WHEN** the user clicks Reset while a non-default component type is selected
- **THEN** the selected component type is unchanged and its fields remain rendered (now blank)

#### Scenario: Reset is blocked during a run

- **WHEN** a Search or AI Search is in progress
- **THEN** the Reset control is disabled and cannot clear the form until the run finishes

### Requirement: Animated loading indicator during a run

While a Search or AI Search is in progress the window SHALL display an animated loading indicator — a rotating-arc spinner drawn on a themed `tk.Canvas`, requiring no image or GIF asset — so the user has a living sign that work is underway, in place of a static text-only message. The indicator SHALL start when the run begins and SHALL stop and be hidden when results are delivered or an error is reported. The indicator SHALL be driven only on the UI thread; background worker threads SHALL NOT touch it directly.

#### Scenario: Indicator animates during a search

- **WHEN** the user starts a Search or AI Search
- **THEN** an animated loading indicator is shown and animates while the background work runs

#### Scenario: Indicator stops when the run ends

- **WHEN** the run completes with results, finds nothing, or fails with an error
- **THEN** the animated indicator stops and is hidden

### Requirement: Live AI Search activity stream

During an AI Search the window SHALL surface the engine's live progress as a "thinking" activity line that updates in real time as the AI works, reflecting the text streamed by `run_demo_search`'s `on_text` callback (which the GUI currently discards). The streamed text SHALL be delivered from the worker thread to the UI thread through the existing `_result_queue` and rendered only on the UI thread by the queue poller; the worker SHALL NOT update any widget directly. The activity line SHALL be cleared when the AI Search finishes, whether it succeeds or fails. The deterministic Search flow SHALL NOT show a streamed activity line (it has no such stream); it shows only the animated indicator.

#### Scenario: AI Search shows live activity as it works

- **WHEN** an AI Search is running and the engine streams progress text
- **THEN** the window shows the latest streamed activity, updating in real time, without the UI freezing

#### Scenario: Streamed updates cross threads safely

- **WHEN** the AI worker thread receives streamed text
- **THEN** it enqueues the text on `_result_queue` and the UI thread renders it in the poller
- **AND** no widget is modified from the worker thread

#### Scenario: Activity line clears when AI Search ends

- **WHEN** an AI Search completes or fails
- **THEN** the live activity line is cleared and the animated indicator is hidden
