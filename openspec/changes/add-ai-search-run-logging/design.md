## Context

The AI Search run is driven by `run_rf_search_pipelined` in `rf_finder/agent/skill_runner.py`: `rf-discovery` streams `@@CANDIDATE@@` lines and one `rf-verify` runs per candidate (bounded by a semaphore, so verifies run concurrently). Both `run_agent_skill` and the conductor loop already iterate the Agent SDK message stream, but they read only `block.text`; everything else — `ToolUseBlock`, `ServerToolUseBlock`, `ToolResultBlock`, and most of `ResultMessage` — is dropped. The GUI worker passes `on_text=lambda _t: None` ([gui.py](../../../rf_finder/ui/gui.py)), so even the text (including discovery's coverage statement) is discarded. Net result: a run leaves no trace, and there is no way to answer "which sites did it visit, what did it find, what did it reject and why".

The installed `claude_agent_sdk` exposes exactly the block types needed: `ToolUseBlock(id, name, input)`, `ServerToolUseBlock(id, name, input)`, `ToolResultBlock(tool_use_id, content, is_error)`, and `ResultMessage` (subtype, usage, num_turns). The data is already flowing through code we own; we are only choosing to capture it.

Constraint from the user: the GUI form must not change (no panels, no buttons), the skills must stay "clean", logging must be toggleable without editing a skill, and all logging logic must live in one place.

## Goals / Non-Goals

**Goals:**
- Capture a complete, structured, replayable record of an AI Search run: tool calls (sites), candidates, rejections + reasons, coverage, cost.
- Real-time visibility from the terminal the app runs in, and a durable per-run log + summary on disk.
- One on/off switch in `.env`; all machinery in one Python module; skills untouched by default.
- Counts and "who/why" derived from structured events, never from scraping model prose.

**Non-Goals:**
- No GUI changes of any kind (no activity panel, no "open logs" button).
- No capture of the model's internal reasoning (`ThinkingBlock`) in this change.
- No log retention/rotation/cleanup policy (files accumulate; addressed later).
- No change to what the search returns, nor to the deterministic (non-AI) Search path.

## Decisions

### D1 — One event stream, two sinks (not two parallel mechanisms)

Every meaningful action becomes one typed event; the single stream fans out to (a) a live console printer and (b) a JSONL file writer. Rationale: a single source of truth means the live view and the saved file can never disagree, and a summary computed from the same events can never disagree with either. Alternative rejected: separate "print as you go" and "write a log at the end" paths — they drift, and the end-of-run writer loses everything if the run crashes.

### D2 — Tap the SDK message stream; take sites from the tool call, not the prose

Extend the existing message loops to inspect all content blocks. `ToolUseBlock`/`ServerToolUseBlock` → `tool_call` (name + URL/query); `ToolResultBlock.is_error` → `tool_result`; `ResultMessage` → `agent_finished`. Rationale: the tool call is ground truth for "which site" — the model's narration is not. Both `ToolUseBlock` and `ServerToolUseBlock` are captured because WebSearch/WebFetch may arrive as server-side tools. Alternative rejected: reconstruct activity by parsing the assistant's text — unreliable and exactly the failure mode we are trying to escape.

### D3 — Real-time via stdout, not a GUI panel

The live feed is printed to stdout, so the developer watching the terminal that launched `python -m rf_finder` sees actions stream by. Rationale: the user explicitly wants a clean form and is comfortable in her code/terminal; stdout needs zero GUI surface. Trade-off: a windowed build with no console shows no live feed — acceptable because the `events.jsonl` file is always written and can be tailed. Alternative rejected: a Tk activity pane — rejected by the user as not clean.

### D4 — Single `RF_LOG` switch, resolved only in Python, mirroring `RF_SKILL_MODE`

A new `.env` variable `RF_LOG` gates the whole subsystem, resolved by a small helper next to the existing `_test_mode()`. One switch controls both sinks. Rationale: consistent with the existing real/test toggle; keeps control in one obvious place. The skills never read it (see D6).

### D5 — Machinery isolated in `rf_finder/agent/run_log.py`; conductor forwards via an `on_event` seam

A new module owns the event dataclass/dict schema and a `RunLogger` that opens the run directory, writes `events.jsonl` (flushed per event), prints the console line, and writes `summary.md` at the end. The conductor gains an `on_event` callback exactly like the existing `on_component`/`on_tokens` seams and calls it at each capture point; when `RF_LOG` is off the callback is a no-op sink. Rationale: the conductor stays about orchestration; formatting/paths/files live in one testable place; reuses the proven worker-thread → callback plumbing.

### D6 — Skills stay dumb; `@@REJECT@@` / `rejected[]` are a separable enhancement

The two structured-reject additions are the skills *completing their honest report of decisions*, symmetric to the existing `@@CANDIDATE@@`. The skills always emit these markers; Python decides whether to capture based on `RF_LOG`. Rationale: keeps all control in Python and lets the user delete a single clearly-fenced block from a skill to revert, without touching Python. The Python capture layer is built and works first (deriving reject reasons from narration); the markers only upgrade reject fidelity and add site-screen rejects. Trade-off: when logging is off the skills still emit a few `@@REJECT@@` lines that Python ignores — negligible token cost.

### D7 — `events.jsonl` (append-only, per-event flush) + end-of-run `summary.md`

Ground truth is line-delimited JSON (one event per line): append-only, crash-tolerant, machine- and human-readable, and the natural shape for a live-tailed stream. The `summary.md` is a derived digest written once at the end. Rationale: keep the durable record dumb and complete; compute the readable rollup from it.

## Risks / Trade-offs

- **Silent verify drops today** ([skill_runner.py](../../../rf_finder/agent/skill_runner.py) swallows a failed verify) → the tap MUST emit an `agent_finished`/`verify_result` error event in the `except` path so a dropped candidate becomes visible instead of vanishing.
- **Concurrent verifies interleave in the file and console** → every event carries an agent id (`verify[<model>]`) and a per-run sequence number so the interleaving is unambiguous on read-back.
- **No console in a windowed build** → the file sink is always written; the live feed is a bonus, not the system of record.
- **Server vs client tool blocks** → capture both `ToolUseBlock` and `ServerToolUseBlock`; branch on `name` to normalize the target field.
- **Unbounded `runs/` growth** → out of scope here; flagged as an open question (retention).
- **Skill token cost when logging off** (always-emitted `@@REJECT@@`) → negligible; not gated to keep the skill dumb.

## Migration Plan

1. Land `run_log.py` + the conductor `on_event` seam + the SDK-block tap + `RF_LOG` resolver. This alone delivers sites/candidates/verify-results/coverage/cost and narration-derived reject reasons — **zero skill edits**.
2. Repurpose the GUI worker's discarded `on_text` into an event forwarder (no form change) so console + file work when launched from the GUI too.
3. Add the fenced `@@REJECT@@` block to `rf-discovery` and the `rejected[]` array to `rf-verify` + `COMPONENT_SCHEMA` — the structured-reject enhancement.

Rollback: set `RF_LOG=off` (instant, no code change), or revert the module/seam. The skill markers are a self-contained deletable block.

## Open Questions

- **Retention/cleanup** of `runs/<timestamp>/` — keep-last-N, age-out, or manual? (Deferred.)
- **`RF_LOG` accepted tokens** — `on`/`off` only, or also `1`/`true`/a path override for the run directory location?
- **Run directory location** — repo-local `runs/` vs a user-data/temp dir; repo-local is simplest for a developer but should be `.gitignore`d.
- **Future `ThinkingBlock` capture** behind a separate, default-off flag if deeper transparency is ever wanted.
