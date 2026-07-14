## Why

We want the desktop app to be able to run an RF component search **through a Claude Skill** — a Skill invoked via the Claude Agent SDK becomes an alternative search engine that finds components, alongside the deterministic adapter pipeline. The end goal is a form button that launches the real `rf-component-search` Skill and shows the components it finds in the **same results table** as the regular search, driven by the **same form** the user already filled.

This change delivers the two durable pieces of that goal — **the form button and the Claude Agent SDK plumbing that wraps a Skill** — and proves them end-to-end *now* against a trivial placeholder Skill that returns a few sample components, so the button → SDK → Skill → results-table path is verified in this project before the real search Skill is wired in. The wrapper is already written and proven in a separate learning project; here we port it and connect it to the button. Because the button calls a generic "run this Skill" wrapper, swapping the placeholder for the real `rf-component-search` Skill later is a config change, not a GUI change.

## What Changes

- **New agent-skill integration** (`rf_finder/agent/skill_runner.py`): a ported, proven `run_agent_skill(prompt, *, skills, allowed_tools, model, on_text=print, output_format=None)` — the single place that talks to Claude via the Agent SDK (`query()` + `ClaudeAgentOptions`). It is skill-agnostic (it knows only skill *names* and *allowed tools*). Three small additions to the proven wrapper: an injectable `on_text` sink (so a caller can redirect/silence the stream), an optional `output_format` passthrough (a JSON-schema so the run returns structured data), and returning the run's **structured result** (`ResultMessage.structured_output`) when a schema was requested, else the final text (`ResultMessage.result`). A thin `run_demo_search(spec_text)` convenience runs the placeholder skill (on `haiku`) with a component-list schema.
- **New placeholder skill** `.claude/skills/demo-component-search/` (`SKILL.md` + a bundled script emitting sample components as JSON): returns 2–3 sample components so the skill → structured-output → table path can be proven. English-only, no emoji, mirroring the existing `word-counter` skill pattern. It is a stand-in for the real `rf-component-search` Skill.
- **New GUI button** "AI Search", next to Search: it reads the **same form** through the **same** `collect(...)` seam Search uses (no separate inputs — the search parameters are shared), formats them into the Skill prompt, runs the Skill on a background thread (reusing the existing `_result_queue`/`_poll_queue` pattern with new message kinds), and renders the returned components into the **same results table**. No dialog, no separate window. The existing Search flow and its result rendering are untouched; Tk is only ever touched from the UI thread.
- **New optional dependency group** `agent = ["claude-agent-sdk>=0.1.0", "python-dotenv>=1.0.0"]` in `pyproject.toml`. Not required to run the existing deterministic search.
- **New standalone smoke-test** `scripts/run_demo_search.py` (with `sys.stdout.reconfigure(encoding="utf-8")`) so the SDK connection and structured output can be proven from the terminal, independent of Tkinter.

## Capabilities

### New Capabilities
- `agent-skill-integration`: The Claude Agent SDK wrapper that runs a named Skill from the app — building `ClaudeAgentOptions` (project + user skill discovery, allowed tools, model, accept-edits, optional structured `output_format`), streaming assistant text through an injectable `on_text` sink, and returning the run's structured result (or final text). It stays skill-agnostic so the placeholder `demo-component-search` and the future `rf-component-search` Skill run through the exact same plumbing.

### Modified Capabilities
- `desktop-gui`: Adds a second search action to the window — an "AI Search" button that reuses the same form/`collect` seam as Search (shared input), runs a Claude Skill on a background thread without freezing the UI, and renders the components the Skill returns into the same results table. The existing Search action and its rendering are unchanged.

## Impact

- **New code:** `rf_finder/agent/__init__.py`, `rf_finder/agent/skill_runner.py`; `.claude/skills/demo-component-search/SKILL.md` and its bundled sample-components script; `scripts/run_demo_search.py`.
- **Modified code:** `rf_finder/ui/gui.py` — one new button + handler, a background worker, a small "render skill components into the existing table" method, and new `_poll_queue` message kinds (`skill_done` / `skill_error`). No change to `_on_search`, the search worker, or the existing `_deliver_results` rendering.
- **Dependencies:** one new optional group (`agent`): `claude-agent-sdk` (+ optional `python-dotenv`). No explicit key needed when logged into Claude Code — the SDK uses that login (precedence `ANTHROPIC_API_KEY` → `CLAUDE_CODE_OAUTH_TOKEN` → `~/.claude/.credentials.json`); an unauthenticated/failed run surfaces as an error in the UI, not a crash.
- **Out of scope:** wiring the real `rf-component-search` Skill and its Excel/tooling flow (a later change); any change to the deterministic search pipeline or the verifier; persisting or exporting the Skill's output.
