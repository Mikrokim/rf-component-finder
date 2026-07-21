## 1. Config switch (RF_LOG)

- [x] 1.1 Add `RF_LOG` to `.env` (and `.env` example if present) next to `RF_SKILL_MODE`, defaulting to off.
- [x] 1.2 Add a `_logging_enabled()` resolver in `rf_finder/agent/skill_runner.py` (mirroring `_test_mode()`) that reads `RF_LOG` and returns a bool; treat unset/empty/unknown as off.
- [x] 1.3 Unit test: `_logging_enabled()` returns True only for the enabled token, False otherwise (monkeypatch env).

## 2. Event model + RunLogger module

- [x] 2.1 Create `rf_finder/agent/run_log.py` with an event schema (kind, agent_id, seq, timestamp, payload) and the event kinds: `tool_call`, `tool_result`, `candidate_found`, `verify_result`, `agent_finished`, `coverage`, `run_started`, `run_finished`.
- [x] 2.2 Implement `RunLogger`: on start, create `runs/<timestamp>/` and open `events.jsonl`; expose `emit(event)` that assigns the next per-run sequence number, writes one JSON line flushed immediately, and prints one console line.
- [x] 2.3 Implement the console line formatter: actions + candidates + rejections only, one line per event, tagged with agent id (e.g. `[verify:BLB28] result → kept`).
- [x] 2.4 Implement a no-op logger (or `emit` short-circuit) used when `RF_LOG` is off, so callers are unconditional.
- [x] 2.5 Add `runs/` to `.gitignore`.
- [x] 2.6 Unit test: `emit` assigns increasing seq numbers, writes one valid JSON object per line, and flushes (file readable mid-run).

## 3. Capture the SDK message stream

- [x] 3.1 In `run_agent_skill`, iterate ALL content blocks (not just text): map `ToolUseBlock`/`ServerToolUseBlock` → `tool_call` (name + URL/query from `input`), `ToolResultBlock` → `tool_result` (with `is_error`), and `ResultMessage` → `agent_finished` (subtype, is_error, num_turns, token totals). Accept an `on_event` callback and emit through it.
- [x] 3.2 In `run_rf_search_pipelined`, thread `on_event` into discovery and every `_verify` call, tagging each with its agent id (`discovery` / `verify[<model>]`).
- [x] 3.3 Emit a `candidate_found` event (with the `screened` array) at the point `_extract_candidates` yields a candidate.
- [x] 3.4 Emit a `verify_result` event when a verify returns — kept (with the returned components) or rejected (empty result).
- [x] 3.5 In the verify `except` path (currently a silent drop), emit a `verify_result` error event so dropped candidates become visible.
- [x] 3.6 Emit a `coverage` event carrying discovery's verbatim final coverage text/structured output.
- [x] 3.7 Recognize the datasheet runner in `tool_call`: when a `Bash` command runs `run_extract.py`, surface it as a datasheet-read (Gemini) action with the `--url` and `--params` parsed out, and pair it with its `tool_result` (success/failure) so the start and end of each Gemini read are visible.
- [x] 3.8 Construct the `RunLogger` (or no-op) once per run from `_logging_enabled()` and pass its `emit` as `on_event`.

## 4. Wire the GUI worker (no form change)

- [x] 4.1 No GUI change needed: the conductor owns the `RF_LOG`-driven logger and prints the live feed to stdout, so `_skill_worker` ([gui.py](../../../rf_finder/ui/gui.py)) is untouched and the form is unchanged — satisfying "logging does not alter the GUI".
- [ ] 4.2 Manually verify launching via `python -m rf_finder` with `RF_LOG=on` shows the live console feed and writes `runs/<timestamp>/events.jsonl`.

## 5. Run summary

- [x] 5.1 At run end, generate `summary.md` in the run directory from the captured events: distinct sites visited, found count, rejected count, each rejection's reason, verbatim coverage, total tokens/turns. Counts derived from events, not prose.
- [x] 5.2 Unit test: given a fixed list of events, `summary.md` reports the correct derived counts and lists each rejection reason.

## 6. Structured rejection reasons (skill enhancement)

- [x] 6.1 Add a clearly-fenced, deletable block to `.claude/skills/rf-discovery/SKILL.md` instructing it to emit `@@REJECT@@ {model, manufacturer, param, site_value, reason}` for a Step 2.7 site-screen drop, symmetric to `@@CANDIDATE@@`.
- [x] 6.2 Parse `@@REJECT@@` lines in the conductor (symmetric to `_extract_candidates`) into rejection events.
- [x] 6.3 Extend `COMPONENT_SCHEMA` in `skill_runner.py` with an optional `rejected[]` array (model, param, found, required, reason).
- [x] 6.4 Add a clearly-fenced, deletable block to `.claude/skills/rf-verify/SKILL.md` instructing it to populate `rejected[]` for a part it drops.
- [x] 6.5 Record `rejected[]` entries as `verify_result` rejections in the conductor; verify narration-derived rejections still work when the array is absent.

## 7. Verification

- [x] 7.1 End-to-end artifacts confirmed: the automated conductor test (`test_conductor_logs_to_disk_only_when_rf_log_on`) writes real `events.jsonl` + `summary.md` through the full pipeline, and a scripted logger demo produced the live console feed + files including a rejection. (A live `RF_SKILL_MODE=test` run still needs SDK auth + a model call — run it live when desired.)
- [x] 7.2 Confirmed via `test_conductor_logs_to_disk_only_when_rf_log_on`: `RF_LOG=off` produces no `runs/` directory and identical returned components; `RF_LOG=on` writes the run dir.
- [x] 7.3 `openspec validate add-ai-search-run-logging --strict` passes; pytest: 579 passed (`-k "not live"`); the only failures are 2 pre-existing live-network SSL tests unrelated to this change.
