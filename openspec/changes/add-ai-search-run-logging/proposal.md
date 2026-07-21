## Why

The AI Search run (the `rf-discovery` → `rf-verify` pipeline) is a black box: the GUI wires `on_text=lambda _t: None`, so every bit of the agent's narration — which sites it visited, how many candidates it found, which it rejected and why, and the final coverage statement — is discarded, and no log is written anywhere. When a search returns a surprising result (one part, or a part that violates the spec), there is no way to see what the agent actually did. Full transparency into the run is a hard requirement before we can trust or debug it.

## What Changes

- Introduce a single **structured event stream** for an AI Search run: each meaningful action (tool call, candidate found, candidate rejected, agent finished, coverage) becomes a typed event tagged with its agent id, timestamp, and sequence number.
- Tap the SDK message stream where the conductor already reads it, capturing the blocks currently thrown away (`ToolUseBlock`/`ServerToolUseBlock`, `ToolResultBlock`, `ResultMessage`) in addition to text — so "which site did it visit" comes from the real tool call, not the model's prose. Found/rejected **counts are derived from events**, never scraped from prose.
- Emit the stream to **two sinks at once**: a live console/stdout feed (real-time visibility from the terminal the app is launched in) and an append-only `events.jsonl` file written live to disk, plus a human-readable `summary.md` generated at run end.
- Add a single on/off switch as an **environment variable** (`RF_LOG`) alongside the existing `RF_SKILL_MODE` in `.env`. One switch controls both sinks; when off, the Python layer discards everything. Logging is never toggled by editing a skill.
- Keep all logging machinery in **one Python module** (`rf_finder/agent/run_log.py`). The GUI form is **not** changed at all (no activity panel, no buttons).
- **Enhancement (separable):** two small, clearly-fenced skill additions so reject reasons become fully structured — `rf-discovery` emits a `@@REJECT@@` line for site-screen drops, and `rf-verify`'s output schema gains a `rejected[]` array. The skills never read `RF_LOG`; they always emit, and Python decides whether to capture. Without these, reject reasons are still captured from narration prose.

## Capabilities

### New Capabilities
- `ai-search-observability`: Structured, toggleable logging of an AI Search run — the event model, the console + `events.jsonl` + `summary.md` sinks, the `RF_LOG` switch, and the contract for what each run must record (sites visited, candidates found, rejections with reasons, coverage, cost).

### Modified Capabilities
<!-- None: the existing merged specs (result-verification, structured-form-input, etc.) do not change their requirements. This change is purely additive observability around the agent pipeline, which has no merged spec to modify. -->

## Impact

- **New file:** `rf_finder/agent/run_log.py` (event schema + `RunLogger`).
- **Modified:** `rf_finder/agent/skill_runner.py` — `run_agent_skill` and `run_rf_search_pipelined` gain an event tap and thread an `on_event` sink; `@@REJECT@@` parsing added symmetric to `@@CANDIDATE@@`; `COMPONENT_SCHEMA` gains an optional `rejected[]` array.
- **Modified (config):** `.env` / `.env` loading gains the `RF_LOG` variable; a small resolver mirrors `_test_mode()`.
- **Modified (skills, fenced/optional):** `.claude/skills/rf-discovery/SKILL.md` (emit `@@REJECT@@`), `.claude/skills/rf-verify/SKILL.md` (populate `rejected[]`).
- **Unchanged:** `rf_finder/ui/gui.py` form layout (only the discarded `on_text` callback is repurposed to forward events).
- **Dependencies:** none added — uses the already-installed `claude-agent-sdk` block types and the stdlib (`json`, `os`, `datetime`).
- **Disk:** a `runs/<timestamp>/` directory per logged run; retention/cleanup is out of scope (documented as an open question).
