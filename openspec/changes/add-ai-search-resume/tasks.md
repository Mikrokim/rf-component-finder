## 1. Event model extensions (`run_log.py`)

- [x] 1.1 Add `spec_text` to the `RUN_STARTED` event payload and ensure it is persisted to `events.jsonl` (the logger already passes arbitrary fields through — confirm and document).
- [x] 1.2 Add an `outcome` field to `VERIFY_RESULT` events (`kept` | `rejected_mismatch` | `failed_infra`) and carry it through `emit`.
- [x] 1.3 Support a `reused: true` flag on any event and ensure it is written to `events.jsonl`.
- [x] 1.4 Update `render_summary` so reused events contribute to counts/sections identically to freshly-executed ones (a resumed run's `summary.md` covers both); optionally mark reused entries visibly.

## 2. Resume switch (`skill_runner.py`)

- [x] 2.1 Add `_resume_enabled()` mirroring `_logging_enabled()` — only the literal `on` (case/whitespace-tolerant) enables it, read from `RF_RESUME`.
- [x] 2.2 Document `RF_RESUME` in `.env` alongside `RF_LOG`, stating the two are independent and that resume with no matching logs runs fresh.

## 3. Resume-state reader (new `rf_finder/agent/resume.py`)

- [x] 3.1 Enumerate `runs/` directories, sort by timestamped name, take the 4 most-recent.
- [x] 3.2 Parse each candidate directory's `events.jsonl` tolerantly (skip unparseable lines), extracting `RUN_STARTED.spec_text`, discovery `AGENT_FINISHED.is_error`, `CANDIDATE_FOUND` (model/manufacturer/url/screened), and `VERIFY_RESULT` (model/outcome).
- [x] 3.3 Filter to runs whose `spec_text` equals the current query's `spec_text`.
- [x] 3.4 Reconstruct merged state across matching runs: `discovery_clean` = any matching run finished discovery cleanly; per-candidate newest verdict wins; expose reusable candidate list + per-candidate final outcomes.
- [x] 3.5 Classify each reconstructed verify outcome as final (`kept`/`rejected_mismatch`) vs `failed_infra`, including detecting the "insufficient verification" marker text; centralize this classification in one helper.
- [x] 3.6 Return a `ResumeState` object (discovery_clean, candidates-to-load, seed `seen` keys, final verdicts to pass through / reuse, kept results) plus the source events to seed forward.

## 4. Conductor integration (`skill_runner.py`)

- [x] 4.1 Store `spec_text` on the emitted `RUN_STARTED` event.
- [x] 4.2 When `RF_RESUME` is on, load `ResumeState` before discovery; when off, skip loading entirely.
- [x] 4.3 Seed the conductor's `seen` set and the reused kept-results/verdicts from `ResumeState`; emit the carried-over `CANDIDATE_FOUND` / final `VERIFY_RESULT` events tagged `reused: true`.
- [x] 4.4 If `discovery_clean`, skip the discovery agent entirely and spawn verifies only for candidates without a final prior outcome; otherwise run discovery as today but suppress re-verify for already-final candidates (via `seen` + verdict seeding).
- [x] 4.5 In `_verify`, classify the produced `VERIFY_RESULT.outcome` using the shared helper (hard exception → `failed_infra`; "insufficient verification" / provider-not-registered → `failed_infra`; genuine param mismatch → `rejected_mismatch`; kept → `kept`).
- [x] 4.6 Ensure kept results reused from prior runs reach `on_component` / the final `{"components": [...]}` exactly like freshly-verified ones, with no duplication against re-run results.

## 5. Tests

- [x] 5.1 `tests/test_resume.py`: directory enumeration + 4-run window; `spec_text` filtering; tolerant `events.jsonl` parsing; merge rules (newest-verdict-wins, any-clean-discovery); outcome classification incl. "insufficient verification" → `failed_infra`.
- [x] 5.2 Extend `tests/test_run_log.py`: `spec_text` on `RUN_STARTED`, `outcome` on `VERIFY_RESULT`, `reused` flag persisted, `render_summary` includes reused events.
- [x] 5.3 Extend `tests/test_skill_runner.py`: resume off = fresh run; resume on + clean prior discovery = discovery skipped and kept candidates passed through; resume on + incomplete prior discovery = discovery re-runs but settled verifies are not repeated; resume on + no matching logs = fresh, no error; `failed_infra` candidates are re-verified.

## 6. End-to-end verification

- [x] 6.1 Reproduce the motivating case with `RF_SKILL_MODE=test`: run a query (logs written), simulate all-verify-`failed_infra`, then re-run with `RF_RESUME=on` and confirm discovery is skipped and only the failed verifies re-run.
- [x] 6.2 Confirm the resumed run creates its own `runs/<timestamp>/` with a complete `summary.md` covering reused + fresh work.
