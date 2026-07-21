## ADDED Requirements

### Requirement: Logging is toggled by an environment variable

The system SHALL read a single environment variable `RF_LOG` (loaded from `.env`, alongside `RF_SKILL_MODE`) to decide whether AI Search run logging is active. When `RF_LOG` is off (unset, empty, or any value other than the enabled token), the Python layer SHALL discard every event and produce no console feed and no files. When `RF_LOG` is on, the same single switch SHALL enable BOTH sinks (console feed and files). The switch SHALL be resolved only in Python; no skill SHALL read `RF_LOG` or otherwise change behavior based on it.

#### Scenario: Logging disabled produces no output

- **WHEN** an AI Search run executes with `RF_LOG` off
- **THEN** no `runs/<timestamp>/` directory is created
- **AND** no run events are printed to the console
- **AND** the search results returned to the GUI are unchanged from a run with no logging

#### Scenario: One switch enables both sinks

- **WHEN** an AI Search run executes with `RF_LOG` on
- **THEN** run events are printed to the console feed
- **AND** an `events.jsonl` file is written for the same run

#### Scenario: Skills are independent of the switch

- **WHEN** `RF_LOG` is toggled between on and off
- **THEN** the text/markers a skill emits are identical in both cases
- **AND** only the Python layer's decision to capture or discard differs

### Requirement: Structured run event model

The system SHALL represent each meaningful run action as a typed event. Every event SHALL carry at least: an event kind, the emitting agent id (`discovery`, or `verify[<model>]` for a per-candidate verify), a timestamp, and a monotonically increasing sequence number within the run. The sequence number and agent id SHALL make the interleaved output of concurrently-running verify agents unambiguous when read back.

#### Scenario: Every event is attributable and ordered

- **WHEN** any run event is emitted
- **THEN** it records its kind, agent id, timestamp, and sequence number

#### Scenario: Concurrent verifies remain distinguishable

- **WHEN** two verify agents run concurrently and emit events
- **THEN** each event's agent id identifies which candidate's verify produced it
- **AND** the per-run sequence numbers impose a total order on the interleaved events

### Requirement: Capture ground-truth actions from the SDK message stream

The system SHALL tap the Agent SDK message stream at the points the conductor already consumes it, and capture the block types currently discarded in addition to text. A `ToolUseBlock` or `ServerToolUseBlock` SHALL produce a `tool_call` event recording the tool name and its target (the fetched URL or search query). A `ToolResultBlock` SHALL produce a `tool_result` event recording whether it was an error. A `ResultMessage` SHALL produce an `agent_finished` event recording the completion subtype, error flag, turn count, and token totals. The site an agent visited SHALL be taken from the actual tool call, never inferred from the model's prose.

#### Scenario: A web fetch is recorded as a tool_call

- **WHEN** an agent invokes a web-fetch/web-search tool
- **THEN** a `tool_call` event records the tool name and the URL or query

#### Scenario: A failed fetch is visible

- **WHEN** a tool result comes back flagged as an error (e.g. a datasheet returns 403)
- **THEN** a `tool_result` event records the failure for that tool call

#### Scenario: Agent completion cost is recorded

- **WHEN** an agent (discovery or a verify) finishes
- **THEN** an `agent_finished` event records its subtype, error flag, turns, and token totals

#### Scenario: A datasheet read via Gemini is surfaced explicitly

- **WHEN** a verify agent invokes the datasheet runner (a `Bash` tool call running `run_extract.py`) to read a datasheet via Gemini
- **THEN** the `tool_call` event is recognized and surfaced as a datasheet-read (Gemini) action, recording the datasheet URL and the requested parameters — not left as an opaque shell command
- **AND** the corresponding `tool_result` records whether the extraction succeeded or failed

### Requirement: Record candidates and rejections with counts derived from events

The system SHALL emit a `candidate_found` event, carrying the candidate's `screened` array, for each `@@CANDIDATE@@` the discovery stream produces, and a `verify_result` event recording kept-vs-rejected for each candidate's verify. Aggregate counts (how many found, how many rejected) reported in any summary SHALL be derived by counting these structured events, and SHALL NOT be parsed from the model's prose coverage statement. The verbatim coverage statement SHALL be captured separately as a `coverage` event for human context only.

#### Scenario: Each streamed candidate is recorded

- **WHEN** discovery emits an `@@CANDIDATE@@` line
- **THEN** a `candidate_found` event records the model, manufacturer, url, and `screened` array

#### Scenario: Counts come from events, not prose

- **WHEN** a summary reports the number of candidates found and rejected
- **THEN** those numbers equal the count of `candidate_found` and rejection events
- **AND** they are not read from the coverage statement text

### Requirement: Emit the event stream to a live console feed and a durable file

The system SHALL emit each event, as it occurs, to two sinks simultaneously: a live console/stdout feed and an append-only `events.jsonl` file under a per-run `runs/<timestamp>/` directory. The `events.jsonl` file SHALL be flushed per event so a run interrupted mid-way still leaves a readable partial log. The console feed SHALL show actions, candidates, and rejections (not the model's internal reasoning), one line per event.

#### Scenario: Events appear live in the console

- **WHEN** an AI Search run is in progress with logging on
- **THEN** each action, candidate, and rejection prints to the console as it happens

#### Scenario: The file survives an interrupted run

- **WHEN** a run is stopped or crashes partway through
- **THEN** `events.jsonl` contains every event emitted up to that point, one JSON object per line

### Requirement: Generate a human-readable run summary at completion

At the end of a logged run the system SHALL write a `summary.md` in the run directory, derived from the captured events, containing: the distinct sites/sources visited, the number of candidates found and the number rejected, each rejection with its reason, the verbatim coverage statement, and the run's token/turn cost.

#### Scenario: Summary reflects the run

- **WHEN** a logged run completes
- **THEN** `summary.md` lists the visited sites, the found/rejected counts, each rejection's reason, the coverage statement, and the total cost

### Requirement: Structured rejection reasons via skill-emitted markers

The system SHALL support fully-structured rejection records supplied by the skills as an enhancement layer over the Python capture. The `rf-discovery` skill SHALL emit a `@@REJECT@@` line — carrying the model, manufacturer, the failing parameter, its site value, and the reason — for a part dropped at the Step 2.7 site screen, symmetric to `@@CANDIDATE@@`. The `rf-verify` skill's structured output SHALL include a `rejected` array in which a dropped part carries a structured reason (the failing parameter, the datasheet value found, and the required value). The Python layer SHALL parse `@@REJECT@@` lines into rejection events and record `rejected[]` entries as `verify_result` rejections. When these markers are absent, the system SHALL still record rejections captured from agent narration, at lower structure.

#### Scenario: A site-screen drop is captured structurally

- **WHEN** discovery emits a `@@REJECT@@` line for a part it dropped at the site screen
- **THEN** a rejection event records the model, failing parameter, site value, and reason

#### Scenario: A verify rejection carries its reason

- **WHEN** a verify run returns a part in its `rejected` array
- **THEN** a `verify_result` rejection event records the failing parameter, the datasheet value, and the required value

#### Scenario: Missing markers degrade gracefully

- **WHEN** the skills emit no `@@REJECT@@` line and no `rejected` array
- **THEN** the run still logs rejections derived from the agents' narration without error

### Requirement: Logging does not alter the GUI or the search result

Adding run logging SHALL NOT change the GUI form (no new panels, controls, or buttons) and SHALL NOT change the set of components returned by an AI Search. All logging machinery SHALL reside in a single dedicated Python module, and the conductor SHALL forward events to it through a callback seam rather than embedding logging logic inline.

#### Scenario: The form is unchanged

- **WHEN** logging is added
- **THEN** the GUI form's layout and controls are identical to before

#### Scenario: Results are unaffected by logging

- **WHEN** the same search is run with logging on and with logging off
- **THEN** the returned components are the same in both runs
