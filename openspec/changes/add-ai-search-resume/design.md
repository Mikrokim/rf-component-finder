## Context

The AI Search pipeline is the Python conductor `run_rf_search_pipelined` in `rf_finder/agent/skill_runner.py`. It runs the `rf-discovery` skill — which streams `@@CANDIDATE@@` lines and uses only web tools (no Gemini) — then fires one `rf-verify` run per candidate, each of which reads a datasheet via Gemini through `run_extract.py`.

Run logging already exists (`rf_finder/agent/run_log.py`, capability `ai-search-observability`): every run writes `runs/<timestamp>/events.jsonl` (a typed event stream) plus a derived `summary.md`. The `RF_LOG` switch gates whether those files are written. The event stream already carries the ground truth resume needs, with two gaps: the query (`spec_text`) is not stored, and verify outcomes are not classified in a machine-readable way.

The motivating failure: when the Gemini key is unavailable, discovery still succeeds but every `rf-verify` returns "insufficient verification". Re-running the query today repeats the entire discovery sweep and every datasheet read. The user wants a re-run of the same query to continue from the prior run's log.

## Goals / Non-Goals

**Goals:**
- Re-running the same query continues from prior-run logs: skip a cleanly-finished discovery, and skip verifies that already reached a final outcome.
- A second, independent switch (`RF_RESUME`) controls reading/resuming, leaving the existing `RF_LOG` write switch untouched.
- Correctly treat infrastructure failures (dead Gemini / "insufficient verification" / rate-limit) as *not done*, so they are retried rather than silently accepted as settled.
- Keep each `runs/<timestamp>/` directory self-contained: a resumed run's `summary.md` reflects the complete picture.

**Non-Goals:**
- True mid-agent checkpointing of discovery. An LLM agent has no resumable internal state; an incomplete discovery is re-run in full.
- Changing the skills. All resume logic is Python-side. (A structured `outcome` field emitted by `rf-verify` is explicitly deferred as optional hardening.)
- A GUI control. The `RF_RESUME` env var is the interface for this change.
- Any change to how or when logs are written (`RF_LOG` semantics are unchanged).

## Decisions

### D1: Resume lives in the conductor + a new `resume.py` module; skills untouched
The conductor already owns the event log and the discovery→verify pipeline, and the existing design principle is that skills know nothing about logging. Resume follows the same seam. The log *reading* logic (find last 4 runs, parse `events.jsonl`, filter by `spec_text`, reconstruct candidates + verdicts, decide skip-discovery) goes in a new `rf_finder/agent/resume.py` so the conductor stays readable and the reconstruction is unit-testable in isolation.
*Alternative considered:* put reading inline in `skill_runner.py` — rejected for testability and conductor bloat.

### D2: Two independent switches, `RF_LOG` (write) and `RF_RESUME` (read)
`RF_RESUME` is resolved exactly like `_logging_enabled()` (only the literal `on` enables it). The two are decoupled: the natural real-world dependency (you can only resume from logs that were written) is handled gracefully — resume with no matching logs just runs fresh, no error. This matches the user's explicit request to keep the write toggle they already like and add a separate read toggle.
*Alternative considered:* force logging on whenever resume is on (a single coupled flag) — rejected; the user wants to retain independent control of writing.

### D3: Query identity = the form's `spec_text`, stored on `RUN_STARTED`
`gui._format_spec_for_skill` renders a `QuerySpec` into a deterministic pipe-delimited line, already passed as `spec_text` into `run_rf_search`. The same filter always yields the identical string, so it is the natural key. It is stored on the `RUN_STARTED` event and compared by equality.
*Alternative considered:* hashing/normalizing the spec — unnecessary; the form output is already canonical for a given filter.

### D4: Skip-vs-re-run decided by discovery's `AGENT_FINISHED`
Discovery uses no Gemini, so if it finished cleanly (`AGENT_FINISHED` with `is_error` false) its candidate list is complete and reusable; the conductor skips discovery and loads candidates (with their `screened` data, needed by the verify prompt) from `CANDIDATE_FOUND` events. If discovery did not finish cleanly, its candidate list is partial, so discovery is re-run in full — but seeded with the prior `seen` set and verdicts so completed verifies are not repeated. This exactly maps the user's two cases ("fell after discovery" vs "fell mid-discovery").

### D5: Verify reuse keyed on an `outcome` classification
A new `outcome` field on `VERIFY_RESULT` classifies each result as `kept`, `rejected_mismatch`, or `failed_infra`. Only `kept`/`rejected_mismatch` are final. `failed_infra` covers dead Gemini, "insufficient verification", rate-limits, and generic errors, and is always retried. This is the crux of the correctness fix: without it, "insufficient verification" would be mistaken for a settled rejection and never retried.
Classification source (MVP): the conductor already emits every `VERIFY_RESULT` and already catches hard errors (→ `failed_infra`). The "insufficient verification" soft case is detected conductor-side by matching that known marker text in the verify result/reject reason.
*Alternative considered (deferred):* have `rf-verify` emit a structured `outcome` in its output schema — more robust but requires a skill + schema change; recorded as future hardening.

### D6: Cross-run merge — newest verdict wins, any clean discovery counts as clean
Within the up-to-4 matching runs, per candidate the most-recent run's verdict wins, and discovery is treated as clean if at least one matching run finished it cleanly. This maximizes reuse while staying deterministic (ordering is by the timestamped directory name).

### D7: Resumed run writes a fresh `runs/<timestamp>/`, seeded with `reused: true` events
Rather than appending to a prior directory, a resumed run makes its own directory and seeds it with the carried-over `CANDIDATE_FOUND` / final `VERIFY_RESULT` events tagged `reused: true`. `render_summary` already derives its counts from events, so a seeded-plus-fresh event stream yields a complete `summary.md` covering both. This keeps every run directory self-contained and immutable.

## Risks / Trade-offs

- **Text-matching "insufficient verification" is brittle** → The marker is a known, stable phrase (documented as the dead-Gemini signature). Centralize the match in one helper so hardening to a structured `outcome` (D5 alternative) later touches one place. Hard errors are already caught structurally, so only the soft case relies on the string.
- **Reusing a stale `kept` result** → Within the 4-run recency window the market is unlikely to have shifted; a fresh run is always one `RF_RESUME=off` away. Accepted per the user's recency-window intent.
- **Re-running discovery still costs tokens in the mid-discovery case** → Unavoidable without skill-level checkpoints (Non-Goal). Verify reuse still prevents the more expensive datasheet re-reads, so the worst case degrades to "discovery repeats, verifies do not".
- **Directory-name timestamp as the ordering key** → `make_run_logger` already names directories `%Y%m%d_%H%M%S_%f`, which sorts lexicographically in chronological order; resume relies on that existing format.
- **Partially-written / corrupt `events.jsonl`** → The reader parses line-by-line and skips unparseable lines (mirroring the existing tolerant logger), so a crashed prior run degrades to "less reused", never an error.

## Migration Plan

Purely additive. New event fields (`spec_text`, `outcome`, `reused`) are optional and ignored by existing readers; old logs without them simply offer less to resume from. `RF_RESUME` defaults to off, so behavior is unchanged until the user opts in. Rollback = unset `RF_RESUME` (and, if desired, revert the additive fields).

## Open Questions

- None blocking. The one deferred decision (structured `rf-verify` `outcome` vs conductor-side text match) is resolved for MVP in favor of the conductor-side match, with the structured field recorded as future hardening.
