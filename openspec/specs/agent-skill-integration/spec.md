# Agent Skill Integration Specification

## Purpose

Define a thin, skill-agnostic wrapper around the Claude Agent SDK that lets the application run any finished Claude Skill by name. The wrapper owns all SDK configuration (skill discovery, allowed tools, model, permissions, optional output schema), streams assistant progress through an injectable sink so both terminal and GUI callers are served, and returns the run's result as structured data or final text.

## Requirements

### Requirement: Skill-agnostic Agent SDK wrapper

The system SHALL provide `run_agent_skill(prompt, *, skills, allowed_tools, model="opus", on_text=print, output_format=None)` in `rf_finder/agent/skill_runner.py` as the single place that talks to Claude via the Claude Agent SDK. It SHALL build a `ClaudeAgentOptions` configured with the repository root as `cwd`, `setting_sources=["user", "project"]` (so both user-level companion skills and the project's `.claude/skills/` are discoverable), the given `skills`, the given `allowed_tools`, the given `model`, `permission_mode="acceptEdits"`, and — when `output_format` is provided — that `output_format`. It SHALL call `query(prompt=prompt, options=options)` to run the request. The function SHALL know only skill *names*, *allowed tools*, and an optional output schema — never a skill's internal steps — so any finished Skill drops in unchanged by passing its name, required tools, and (optionally) the schema of its result.

#### Scenario: Options are built for project and user skill discovery

- **WHEN** `run_agent_skill` is called with `skills=["some-skill"]` and `allowed_tools=["Skill", "Bash", "Read"]`
- **THEN** the `ClaudeAgentOptions` passed to `query` has `cwd` set to the repository root, `setting_sources == ["user", "project"]`, `skills == ["some-skill"]`, `allowed_tools == ["Skill", "Bash", "Read"]`, and `permission_mode == "acceptEdits"`

#### Scenario: An output schema is forwarded when requested

- **WHEN** `run_agent_skill` is called with an `output_format` JSON schema
- **THEN** that `output_format` is set on the `ClaudeAgentOptions` passed to `query`
- **AND WHEN** `output_format` is omitted, no output format is set on the options

#### Scenario: The wrapper is indifferent to which Skill it runs

- **WHEN** `run_agent_skill` is called with a different `skills`/`allowed_tools`/`model` combination
- **THEN** those exact values are used to build the options, with no wrapper logic branching on the specific skill name

### Requirement: Streamed assistant text routed through an injectable sink

The wrapper SHALL stream progress live: for each assistant text block received during the run it SHALL invoke the `on_text` callback with that text, and it SHALL invoke `on_text` with a terminal completion marker derived from the SDK result message. `on_text` SHALL default to the built-in `print` so standalone/terminal use is unchanged; a caller (the GUI) MAY pass its own callback to redirect or silence the stream. The wrapper SHALL NOT write to any UI object directly.

#### Scenario: Default sink prints (terminal behaviour unchanged)

- **WHEN** `run_agent_skill` is called without an `on_text` argument
- **THEN** each streamed assistant text block and the completion marker are passed to `print`

#### Scenario: Injected sink receives the stream

- **WHEN** `run_agent_skill` is called with `on_text=collector` and the run yields two assistant text blocks
- **THEN** `collector` is invoked with each block in order, followed by the completion marker
- **AND** nothing is written directly to any UI widget by the wrapper

### Requirement: Run result returned as structured data or final text

The wrapper SHALL return the run's result to the caller. WHEN an `output_format` schema was requested and the run produced structured data (`ResultMessage.structured_output`), the wrapper SHALL return that structured data. Otherwise it SHALL return the run's final answer text (`ResultMessage.result`). This lets a caller that requested a schema consume typed results directly, while a plain caller still gets the answer text.

#### Scenario: Structured result returned when a schema was requested

- **WHEN** a run requested an `output_format` and completes with `structured_output` populated
- **THEN** `run_agent_skill` returns that `structured_output` value

#### Scenario: Final text returned when no structured output is present

- **WHEN** a run completes with no `structured_output` (no schema requested)
- **THEN** `run_agent_skill` returns the run's final text (`ResultMessage.result`)
