## ADDED Requirements

### Requirement: Resume switch independent of logging

The system SHALL provide an `RF_RESUME` environment switch that gates only the *reading/resuming* of prior-run logs. It SHALL be independent of the existing `RF_LOG` switch (which gates only the *writing* of logs). Only the explicit `on` token (case-insensitive, whitespace-tolerant) enables resume; unset, empty, or any other value disables it, mirroring how `RF_LOG` is resolved.

#### Scenario: Resume disabled runs fresh

- **WHEN** an AI Search run starts with `RF_RESUME` unset, empty, or set to any value other than `on`
- **THEN** the run ignores all prior-run logs and executes discovery and every verify from scratch

#### Scenario: Resume enabled with no matching logs

- **WHEN** `RF_RESUME` is `on` but no prior run in the lookback window matches the current query
- **THEN** the run proceeds fresh, executing discovery and every verify, and raises no error

#### Scenario: Switches are independent

- **WHEN** `RF_RESUME` is `on` while `RF_LOG` is off
- **THEN** the run still attempts to read prior logs for continuation, and the absence of newly-written logs does not disable or error the resume attempt

### Requirement: Query identity keyed on form spec text

The system SHALL identify "the same query" by the deterministic `spec_text` produced by the form for the pipeline. The `spec_text` SHALL be recorded on the run's `RUN_STARTED` event. Two runs match when their recorded `spec_text` values are equal.

#### Scenario: spec_text recorded at run start

- **WHEN** an AI Search run starts
- **THEN** its `RUN_STARTED` event includes the `spec_text` used for that run

#### Scenario: Same filter matches across runs

- **WHEN** the user submits the same form filter that produced a prior run's `spec_text`
- **THEN** the current run's `spec_text` equals that prior run's recorded `spec_text` and the prior run is eligible for resume

#### Scenario: Different filter does not match

- **WHEN** the current run's `spec_text` differs from a prior run's recorded `spec_text`
- **THEN** that prior run is not used as a resume source

### Requirement: Bounded lookback window

When resume is enabled, the system SHALL consider only the 4 most-recent `runs/` directories ordered by their timestamped directory name. Older directories SHALL be ignored. Among those 4, only directories whose recorded `spec_text` matches the current query SHALL be used as resume sources.

#### Scenario: Only the last four runs are scanned

- **WHEN** more than four `runs/` directories exist and resume is enabled
- **THEN** only the four most-recent by timestamp are examined, and any matching prior run outside that window is ignored

#### Scenario: Matching runs selected within the window

- **WHEN** some of the four most-recent runs have a `spec_text` matching the current query and others do not
- **THEN** only the matching runs are used as resume sources

### Requirement: Discovery reuse keyed on discovery completion

The system SHALL determine whether the prior discovery finished cleanly using discovery's `AGENT_FINISHED` event (`is_error` false and present). When at least one matching prior run finished discovery cleanly, the system SHALL skip discovery entirely and load the candidate list — including each candidate's `model`, `manufacturer`, `url`, and `screened` data — from the log. When no matching prior run finished discovery cleanly, the system SHALL re-run discovery in full.

#### Scenario: Clean prior discovery skips discovery

- **WHEN** a matching prior run has a discovery `AGENT_FINISHED` event with `is_error` false
- **THEN** the current run does not execute discovery and instead loads the prior candidate list from the log

#### Scenario: Incomplete prior discovery re-runs discovery

- **WHEN** no matching prior run has a clean discovery `AGENT_FINISHED` event
- **THEN** the current run executes discovery in full

#### Scenario: Re-run seeds prior work

- **WHEN** discovery is re-run because prior discovery was incomplete
- **THEN** the dedup set and prior verify verdicts are seeded so that any candidate with a final prior outcome is not re-verified

### Requirement: Per-candidate verify reuse keyed on outcome

The system SHALL classify each `VERIFY_RESULT` with an `outcome` of `kept`, `rejected_mismatch`, or `failed_infra`. A prior outcome of `kept` or `rejected_mismatch` is final and the candidate SHALL NOT be re-verified — a `kept` result SHALL be passed through to the current run's results. A prior outcome of `failed_infra` — including Gemini unavailability, the "insufficient verification" case, rate-limit, and generic verify errors — is not final and the candidate SHALL be re-verified. The "insufficient verification" case SHALL be classified as `failed_infra`.

#### Scenario: Kept result is reused

- **WHEN** a matching prior run recorded a candidate's verify outcome as `kept`
- **THEN** the candidate is not re-verified and its kept result is included in the current run's results

#### Scenario: Genuine mismatch is not re-verified

- **WHEN** a matching prior run recorded a candidate's verify outcome as `rejected_mismatch`
- **THEN** the candidate is not re-verified and remains rejected

#### Scenario: Infrastructure failure is re-verified

- **WHEN** a matching prior run recorded a candidate's verify outcome as `failed_infra` (including the "insufficient verification" case)
- **THEN** the candidate is re-verified in the current run

### Requirement: Cross-run merge rules

When more than one matching prior run exists within the lookback window, the system SHALL merge their state: for each candidate the newest recorded verdict (by run timestamp) SHALL win, and discovery SHALL be treated as clean when at least one matching run finished discovery cleanly.

#### Scenario: Newest verdict wins

- **WHEN** two matching prior runs recorded different outcomes for the same candidate
- **THEN** the outcome from the more-recent run is used

#### Scenario: Any clean discovery counts as clean

- **WHEN** at least one matching prior run finished discovery cleanly while another did not
- **THEN** discovery is treated as clean and is skipped

### Requirement: Self-contained resumed run output

A resumed run SHALL create its own new `runs/<timestamp>/` directory. It SHALL seed that directory with the events reused from prior runs, marked with a `reused` flag, so that the run's `summary.md` reflects a complete whole covering both the reused and the freshly-executed work.

#### Scenario: New directory per resumed run

- **WHEN** a run resumes from prior logs
- **THEN** it writes to a new `runs/<timestamp>/` directory rather than modifying any prior run's directory

#### Scenario: Reused events are marked and summarized

- **WHEN** a resumed run seeds candidates and verdicts carried over from a prior run
- **THEN** those seeded events carry a `reused` flag and the resumed run's `summary.md` includes both the reused and the freshly-executed results
