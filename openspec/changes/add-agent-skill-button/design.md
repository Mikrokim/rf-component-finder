## Context

The GUI (`rf_finder/ui/gui.py`) already has the two seams this change needs: `collect(schema, answers=...)` turns the form into a `QuerySpec`, and a background-thread + `queue.Queue` + `root.after` poll (`_result_queue` / `_poll_queue`) hands off-thread work back to the UI thread safely. This change adds a *second search engine* to the same window — a Claude Skill invoked via the Claude Agent SDK — that shares the existing form as its input and the existing results table as its output. Only the engine differs.

The wrapper that talks to the SDK is already written and proven in a separate learning project. Here it is ported as `run_agent_skill`. The Agent SDK's `query()` is `async` and streams messages (Claude works in steps — reason, run a tool, read the result, respond — so a run yields several messages), and Tkinter is single-threaded and not thread-safe — so the same "worker thread + queue" constraint that shaped the Search flow shapes this one.

Reading the installed `claude_agent_sdk` source confirmed the mechanism for structured results: `ResultMessage.structured_output` is populated **only** when `ClaudeAgentOptions.output_format` is set to a JSON schema (`{"type":"json_schema","schema":{...}}`); otherwise the answer arrives as text on `ResultMessage.result`. So to get a clean list of components (rather than prose to parse) the GUI must pass a component schema.

The real destination is a Skill that performs RF component search (`rf-component-search`) and returns the components it finds. This change stops short of that: it wires the button and the plumbing and proves them against a throwaway placeholder Skill that returns a few sample components, so nothing product-facing depends on the placeholder.

## Goals / Non-Goals

**Goals:**
- Port the proven `run_agent_skill` wrapper into `rf_finder/agent/skill_runner.py` with three minimal, backward-compatible additions: an injectable `on_text` sink (default `print`), an optional `output_format` passthrough, and returning `ResultMessage.structured_output` when a schema was requested (else `ResultMessage.result`).
- Add one button, "AI Search", that reuses the **same form** (via the existing `collect` seam) and the **same results table** as deterministic Search, running a Skill on a background thread and rendering the returned components into that table.
- Keep the wrapper and GUI **skill-agnostic** so the later swap to `rf-component-search` is a change of skill name + schema, not GUI code.
- Never freeze or crash the window; keep the deterministic Search flow and its rendering byte-for-byte unaffected.

**Non-Goals:**
- Wiring the real `rf-component-search` Skill or its Excel/tooling flow (a later change).
- Any change to adapters, verifier, form, or the deterministic `search_and_verify` core and its `_deliver_results` rendering.
- A separate output window/dialog, live incremental streaming into the UI, or persisted/exported output.

## Decisions

### D1 — Port the wrapper into `rf_finder/agent/skill_runner.py`, three minimal changes
`run_agent_skill(prompt, *, skills, allowed_tools, model="opus", on_text=print, output_format=None)` is copied from the proven learning-project wrapper. It builds `ClaudeAgentOptions(cwd=PROJECT_ROOT, setting_sources=["user","project"], skills=..., allowed_tools=..., model=..., permission_mode="acceptEdits")`, adds `output_format` when provided, and iterates `query(prompt=prompt, options=options)`. Three small, backward-compatible changes from the proven original:

1. The hard-coded `print(...)` becomes `on_text(...)` (default `print`), so terminal behavior is identical and a caller can redirect or silence the stream.
2. A new optional `output_format` parameter is passed through to the options — the switch that makes the SDK return structured data.
3. The return value becomes `ResultMessage.structured_output` when a schema was requested (else `ResultMessage.result`), so a caller that asked for structure gets typed results, while a plain caller still gets the answer text. (This also retires the earlier incidental "last assistant block" return.)

`PROJECT_ROOT` is computed as the repo root (three parents up from this module) so `.claude/skills/` is discoverable; the learning project used the wrapper file's own dir, which here would be `rf_finder/agent/` — wrong — hence the explicit root.

### D2 — Wrapper and GUI stay skill-agnostic; the placeholder lives outside the durable spec
`run_agent_skill` knows only skill *names*, *allowed tools*, and an optional schema. The demo entry point `run_demo_search(spec_text, *, on_text=print)` calls it with `skills=["demo-component-search"]`, `allowed_tools=["Skill","Bash","Read"]`, `model="haiku"`, the component `output_format` schema, and a prompt built from `spec_text`. **`demo-component-search` and `run_demo_search` are this change's verification vehicle, not a permanent capability** — they are deliberately kept out of the `agent-skill-integration` spec so the durable contract describes only the generic wrapper. When the real Skill lands, a sibling `run_rf_search` is added (or `run_demo_search` repointed) with the same call shape and the same schema — no change to `run_agent_skill` or the GUI.

### D3 — `demo-component-search` placeholder returns sample components; the component schema
A minimal Skill at `.claude/skills/demo-component-search/`: `SKILL.md` (frontmatter `name`/`description`, English-only, "no emoji") plus `scripts/sample_components.py`, invoked as `python3 "${CLAUDE_SKILL_DIR}/scripts/sample_components.py"`, which prints a small fixed JSON list of 2–3 sample components. The SKILL.md instructs Claude to run the script and return those components. With the `output_format` schema set on the run, Claude's final `structured_output` is the component list. This mirrors the known-good `word-counter` shape (a Skill whose "work" is a bundled script) and exercises the exact path the real skill will use. The shared schema:

```
{"type": "json_schema",
 "schema": {"type": "object",
   "properties": {"components": {"type": "array", "items": {"type": "object",
     "properties": {"model": {"type": "string"}, "manufacturer": {"type": "string"},
                    "url": {"type": "string"}, "verdict": {"type": "string"}},
     "required": ["model", "manufacturer", "url"]}}},
   "required": ["components"]}}
```

### D4 — Same form in, same table out; AI Search gets its own render path
AI Search reuses the deterministic Search's input seam verbatim: `_on_run_skill` runs the same `_validate_form` + `collect(self.schema, answers=self.build_answers())` + `ValueError` → `messagebox` as `_on_search`, then formats the `QuerySpec` constraints into a compact pipe-delimited prompt. Output goes into the **same** `Treeview`: a new `_deliver_skill_results(components)` clears the table and inserts one row per returned component (`model`, `manufacturer`, `verdict`, `url`), reusing the existing double-click-to-open-url binding and the "no results" empty-state. The existing `_deliver_results` (which renders `VerifiedCandidate` objects for deterministic Search) is **not** touched — AI Search maps its plain dicts straight to rows, so the two engines share the widget without sharing a data model. No dialog, no second window.

### D5 — Reuse the existing thread + queue; add message kinds, touch nothing else
`_on_run_skill` disables the AI Search button, sets a `self._skill_running` guard, and starts a `threading.Thread`. The worker runs `result = asyncio.run(run_demo_search(spec_text, on_text=lambda _: None))` (no-op sink so step narration doesn't spill to the console), extracts `result["components"]`, and `put`s `("skill_done", components)` — or `("skill_error", exc)` — on the **existing** `_result_queue`. `_poll_queue` gains two branches: `skill_done` → `_deliver_skill_results` (render into the shared table) + re-enable button; `skill_error` → error dialog + re-enable — alongside the untouched `ok`/`error` search branches. Successful results go into the table (no dialog); only failures use a dialog, exactly as the deterministic Search already reports its errors. The worker never touches Tk. Alternative rejected: a separate queue/poller — needless duplication of the 100 ms tick that already exists.

### D6 — Optional dependency + authentication + missing-auth handling
`claude-agent-sdk` and `python-dotenv` go in a new optional group `[project.optional-dependencies] agent = [...]`, so the deterministic search still installs and runs without them. **Authentication needs no explicit API key when Claude Code is logged in**: the SDK resolves credentials in the order `ANTHROPIC_API_KEY` → `CLAUDE_CODE_OAUTH_TOKEN` → the Claude Code login at `~/.claude/.credentials.json` (confirmed in the SDK's `session_resume.py`), so a developer already using Claude Code needs nothing extra. `skill_runner` still optionally loads a `.env` (guarded `try: from dotenv import load_dotenv`) for the API-key path. The SDK import is done inside the worker path, so a missing SDK or an unauthenticated run surfaces as `("skill_error", exc)` → a dialog, never an import crash at GUI startup. Malformed/absent structured output is treated the same way (an error dialog), so the table is never left half-rendered.

### D7 — Standalone smoke-test script
`scripts/run_demo_search.py` (with `sys.stdout.reconfigure(encoding="utf-8")`) calls the same `run_demo_search` with a sample spec and default `print` sink, printing the returned components — so the SDK connection and structured output can be proven from the terminal, isolating "is it the SDK or the Tkinter wiring" before the button is used. It adds the repo root to `sys.path` so it runs as a loose script.

## Risks / Trade-offs

- **Tkinter not thread-safe** → the worker returns only plain data via the existing queue; every widget touch stays on the UI thread (D5), the same rule the Search flow already follows.
- **Async in a thread** → `query()` is async; the worker wraps it in `asyncio.run(...)`, which creates and tears down its own loop per run. Fine for a user-initiated, non-concurrent action.
- **Structured output not guaranteed** → if `structured_output` is absent/malformed on a run, AI Search takes the `skill_error` path and shows a dialog rather than rendering garbage (D6); the real skill will use the same schema, so this path is exercised now.
- **Skill/SDK unavailable at runtime** → missing SDK, missing `ANTHROPIC_API_KEY`, or a run error are caught and shown as a dialog; the deterministic Search keeps working (D6).
- **Placeholder leaking into the durable contract** → avoided by keeping `demo-component-search`/`run_demo_search` in design + tasks only, not in the `agent-skill-integration` spec (D2).
- **Repo-root path assumption** → `PROJECT_ROOT` is derived from the module location; if the module moves, the derivation must move with it (D1). Documented so the later real-skill change doesn't reintroduce the learning-project's `__file__`-dir assumption.
