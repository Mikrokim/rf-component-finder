## 1. Dependencies

- [x] 1.1 Add an optional group to `pyproject.toml`: `[project.optional-dependencies] agent = ["claude-agent-sdk>=0.1.0", "python-dotenv>=1.0.0"]` (`python-dotenv` is optional — only for a `.env` API key; leave the base `dependencies` untouched so deterministic search installs without the SDK)
- [ ] 1.2 (user, terminal) Install into the venv: `py -m pip install claude-agent-sdk`. **No `ANTHROPIC_API_KEY` needed** if you are logged into Claude Code — the SDK authenticates via that existing login (precedence: `ANTHROPIC_API_KEY` → `CLAUDE_CODE_OAUTH_TOKEN` → Claude Code credentials at `~/.claude/.credentials.json`). Set a key only if you want to run outside a Claude Code login.

## 2. Agent-skill wrapper (`rf_finder/agent/`)

- [x] 2.1 Create `rf_finder/agent/__init__.py` exporting `run_agent_skill` and `run_demo_search`
- [x] 2.2 Create `rf_finder/agent/skill_runner.py` and port `run_agent_skill(prompt, *, skills, allowed_tools, model="opus", on_text=print, output_format=None)` from the proven wrapper: build `ClaudeAgentOptions(cwd=PROJECT_ROOT, setting_sources=["user","project"], skills, allowed_tools, model, permission_mode="acceptEdits")`, adding `output_format` only when provided; iterate `query(prompt=prompt, options=options)` (SDK imported lazily inside the function)
- [x] 2.3 Compute `PROJECT_ROOT` as the repo root (three parents up from this module) so `.claude/skills/` is discoverable; optionally `load_dotenv(PROJECT_ROOT/".env")` inside a guarded `try/except`
- [x] 2.4 Stream via `on_text`: forward each `AssistantMessage` text block and a `[done: <subtype>]` marker to `on_text` (default `print`); never touch any UI object
- [x] 2.5 Return `ResultMessage.structured_output` when `output_format` was requested, else `ResultMessage.result`
- [x] 2.6 Define the component `output_format` schema (a `{"type":"json_schema", ...}` for `{"components": [{model, manufacturer, url, verdict}]}`) and `run_demo_search(spec_text, *, on_text=print)` that calls `run_agent_skill(skills=["demo-component-search"], allowed_tools=["Skill","Bash","Read"], model="haiku", output_format=<schema>)` with a prompt built from `spec_text`

## 3. Placeholder skill (`.claude/skills/demo-component-search/`)

- [x] 3.1 Create `.claude/skills/demo-component-search/SKILL.md` (frontmatter `name: demo-component-search` + `description`), instructing Claude to run the bundled script and return the components; "Always respond in English only. Do not use emoji."
- [x] 3.2 Create `.claude/skills/demo-component-search/scripts/sample_components.py` (with `sys.stdout.reconfigure(encoding="utf-8")`) that prints a small fixed JSON list of 2–3 sample components (model, manufacturer, url, verdict)

## 4. Standalone smoke-test

- [x] 4.1 Create `scripts/run_demo_search.py` (with `sys.stdout.reconfigure(encoding="utf-8")`, repo root added to `sys.path`) that calls `run_demo_search(<sample spec>)` with the default `print` sink and prints the returned components
- [x] 4.2 (user, terminal) Run `py scripts/run_demo_search.py`; confirm it prints the sample components and `[done: success]` — proving the SDK connection + structured output before touching the GUI  *(verified: structured_output returned the 3 components; no API key needed — used Claude Code login)*

## 5. GUI wiring (`rf_finder/ui/gui.py`)

- [x] 5.1 Add an "AI Search" `ttk.Button` in the existing `controls` frame next to Search; initialise `self._skill_running = False`
- [x] 5.2 Implement `_on_run_skill`: reuse `_validate_form` + `collect(self.schema, answers=self.build_answers())` + `ValueError` → `messagebox.showerror` exactly like `_on_search`; build the pipe-delimited parameter summary from `spec.constraints`
- [x] 5.3 Add a helper (`_format_spec_for_skill`) that formats a `QuerySpec` into the compact summary string (component type + each constraint), reusing the CLI's range wording (`>=`/`<=`/`a to b`)
- [x] 5.4 Start a `threading.Thread` worker that runs `asyncio.run(run_demo_search(spec_text, on_text=lambda _: None))`, extracts `result["components"]`, and `put`s `("skill_done", components)` / `("skill_error", exc)` on the existing `_result_queue`; import the SDK-facing entry inside the worker so a missing SDK/auth becomes `skill_error`, not a startup crash
- [x] 5.5 Disable the AI Search (and Search) button + set `_skill_running` while running; block a second concurrent AI Search
- [x] 5.6 Extend `_poll_queue` with `skill_done` → `_deliver_skill_results(components)` + re-enable button, and `skill_error` → `messagebox.showerror` + re-enable; leave the `ok`/`error` search branches unchanged
- [x] 5.7 Implement `_deliver_skill_results(components)`: clear the table, insert one row per component (`model`, `manufacturer`, `verdict`, `url`) into the existing `Treeview`, register each row's url for the existing double-click handler, and show the "no components" empty-state when the list is empty — without modifying the existing `_deliver_results`

## 6. Tests

- [x] 6.1 Headless unit tests (no Tk driving, SDK mocked): `run_agent_skill` builds options with the expected `cwd`/`setting_sources`/`skills`/`allowed_tools`/`permission_mode` and forwards `output_format`; returns `structured_output` when a schema was requested, else `result`; `on_text` receives streamed blocks + the done marker — `tests/test_skill_runner.py`
- [x] 6.2 Test the `QuerySpec` → summary formatter (the keystone amplifier example) and that `_deliver_skill_results` maps a component list to the expected rows / shows the empty-state (using the same Tk-skip guard as `tests/test_gui.py`) — added to `tests/test_gui.py`
- [x] 6.3 (user, terminal) Run the full suite: `py -m pytest`  *(new tests: 24 passed, 2 skipped, 0 failed. The only failures in the full run are pre-existing `*_search_live` network tests — threerwave, ums — unrelated to this change, failing on the corporate SSL proxy.)*

## 7. Verify

- [x] 7.1 (user, terminal) Run `py -m rf_finder.ui.gui`: fill the amplifier form, click **AI Search**, confirm the sample components appear in the same results table, double-click opens a url, and the deterministic **Search** still works unchanged  *(verified working; note the sample components' URLs are placeholder/fake and may 404 — real URLs arrive with the real skill)*
- [ ] 7.2 (user, terminal) Confirm failure handling: simulate an unauthenticated/failed run (e.g. log out of Claude Code, or force an SDK error) and click AI Search → an error dialog appears, the button re-enables, and Search still works
- [ ] 7.3 Confirm `python -m rf_finder` (the existing CLI) is unaffected
