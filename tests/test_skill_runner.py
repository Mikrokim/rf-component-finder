"""Headless tests for the Claude Agent SDK wrapper (``rf_finder.agent``).

The SDK is mocked — a fake ``claude_agent_sdk`` module is installed in
``sys.modules`` so ``run_agent_skill`` (which imports it lazily) picks up our
stand-ins. No network, no real model call, no Tk. These lock down the option
building, the structured-vs-text return contract, the ``on_text`` streaming, and
the ``run_rf_search`` configuration.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest


# --- SDK stand-ins ---------------------------------------------------------


class _FakeAssistantMessage:
    def __init__(self, content):
        self.content = content


class _FakeResultMessage:
    def __init__(self, subtype="success", result=None, structured_output=None):
        self.subtype = subtype
        self.result = result
        self.structured_output = structured_output


class _Block:
    def __init__(self, text):
        self.text = text


class _FakeOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_query(messages, captured):
    async def query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        for m in messages:
            yield m

    return query


class _FakeClient:
    """Stand-in for ``ClaudeSDKClient`` (the streaming path). Per test, set the
    class-level ``messages``; inspect ``instances`` for options/interrupt state."""

    messages: list = []
    instances: list = []

    def __init__(self, options=None, transport=None):
        self.options = options
        self.queried = None
        self.interrupted = False
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt, session_id="default"):
        self.queried = prompt

    async def interrupt(self):
        self.interrupted = True

    async def receive_response(self):
        for m in list(_FakeClient.messages):
            yield m


@pytest.fixture(autouse=True)
def _hermetic_skill_mode(monkeypatch):
    """Keep tests independent of the repo ``.env``: default to real mode and
    logging off unless a test sets the env itself. (The app's .env sets these,
    which would otherwise leak into every test here.)"""
    monkeypatch.delenv("RF_SKILL_MODE", raising=False)
    monkeypatch.delenv("RF_LOG", raising=False)


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a fake ``claude_agent_sdk`` module; per-test set ``.query`` (for
    ``run_agent_skill``) or ``_FakeClient.messages`` (for the streaming path)."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.AssistantMessage = _FakeAssistantMessage
    mod.ResultMessage = _FakeResultMessage
    mod.ClaudeAgentOptions = _FakeOptions
    mod.ClaudeSDKClient = _FakeClient
    _FakeClient.messages = []
    _FakeClient.instances = []
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    return mod


# --- Option building -------------------------------------------------------


def test_options_built_for_skill_discovery(fake_sdk):
    from rf_finder.agent.skill_runner import PROJECT_ROOT, run_agent_skill

    captured = {}
    fake_sdk.query = _make_query([_FakeResultMessage(result="hi")], captured)

    asyncio.run(
        run_agent_skill(
            "prompt",
            skills=["some-skill"],
            allowed_tools=["Skill", "Bash", "Read"],
            model="haiku",
            on_text=lambda _t: None,
        )
    )

    opts = captured["options"]
    assert opts.cwd == PROJECT_ROOT
    assert opts.setting_sources == ["user", "project"]
    assert opts.skills == ["some-skill"]
    assert opts.allowed_tools == ["Skill", "Bash", "Read"]
    assert opts.model == "haiku"
    assert opts.permission_mode == "acceptEdits"
    # No schema requested -> output_format not set on the options.
    assert "output_format" not in opts.kwargs


def test_output_format_forwarded_when_given(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    captured = {}
    schema = {"type": "json_schema", "schema": {"type": "object"}}
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": []})], captured
    )

    asyncio.run(
        run_agent_skill(
            "prompt",
            skills=["s"],
            allowed_tools=[],
            output_format=schema,
            on_text=lambda _t: None,
        )
    )

    assert captured["options"].kwargs["output_format"] == schema


# --- Return contract: structured when a schema was requested, else text ----


def test_returns_structured_output_when_schema_requested(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    payload = {"components": [{"model": "X", "manufacturer": "Y", "url": "u"}]}
    fake_sdk.query = _make_query(
        [_FakeResultMessage(result="ignored text", structured_output=payload)], {}
    )

    out = asyncio.run(
        run_agent_skill(
            "p", skills=[], allowed_tools=[],
            output_format={"type": "json_schema", "schema": {}},
            on_text=lambda _t: None,
        )
    )
    assert out == payload


def test_returns_final_text_when_no_schema(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    fake_sdk.query = _make_query(
        [_FakeResultMessage(result="the answer", structured_output=None)], {}
    )

    out = asyncio.run(
        run_agent_skill("p", skills=[], allowed_tools=[], on_text=lambda _t: None)
    )
    assert out == "the answer"


# --- on_text streaming -----------------------------------------------------


def test_on_text_receives_blocks_then_done_marker(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    messages = [
        _FakeAssistantMessage([_Block("first"), _Block("second")]),
        _FakeResultMessage(subtype="success", result="x"),
    ]
    fake_sdk.query = _make_query(messages, {})

    seen: list[str] = []
    asyncio.run(
        run_agent_skill("p", skills=[], allowed_tools=[], on_text=seen.append)
    )

    assert seen[0] == "first"
    assert seen[1] == "second"
    assert any("done" in s and "success" in s for s in seen)


# --- pipelined conductor: rf-discovery (stream) -> one rf-verify per candidate


def test_extract_candidates_buffers_partial_lines():
    from rf_finder.agent.skill_runner import _extract_candidates

    rem, got = _extract_candidates(
        '@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}'
    )
    assert got == []            # no newline yet -> buffered
    rem, got = _extract_candidates(rem + '\n@@CANDIDATE@@ {"model": "M2"}\n')
    assert [c["model"] for c in got] == ["M1", "M2"]
    assert rem == ""


def test_extract_rejects_pulls_reject_lines():
    from rf_finder.agent.skill_runner import _extract_rejects

    rem, got = _extract_rejects('@@REJECT@@ {"model": "M9", "param": "NF"}\nleftover')
    assert [r["model"] for r in got] == ["M9"]
    assert rem == "leftover"


def test_conductor_captures_site_screen_and_verify_rejects(fake_sdk):
    """A `@@REJECT@@` site-screen drop and a verify `rejected[]` entry both become
    rejection events with their reasons, and the run_finished count includes both."""
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    disc_text = (
        '@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n'
        '@@REJECT@@ {"model": "M9", "manufacturer": "Y", "param": "NF", '
        '"site_value": "4.2 dB", "reason": "NF too high"}\n'
    )
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(disc_text)]),
        _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
    ]
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [], "rejected": [
            {"model": "M1", "param": "freq_range", "found": "2.5-7 GHz",
             "required": "2-6 GHz", "reason": "band does not contain 2-6 GHz"}
        ]})],
        {},
    )

    events: list = []
    out = asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None, on_event=events.append))

    site = [e for e in events if e["kind"] == run_log.REJECT]
    assert site and site[0]["model"] == "M9" and site[0]["param"] == "NF"
    vr = [e for e in events if e["kind"] == run_log.VERIFY_RESULT and e.get("status") == "rejected"]
    assert vr and "does not contain" in vr[0]["reason"]
    assert out["components"] == []
    finished = [e for e in events if e["kind"] == run_log.RUN_FINISHED][0]
    assert finished["rejected"] == 2   # one site-screen + one verify


def test_run_rf_search_pipelines_discovery_into_verify(fake_sdk):
    from rf_finder.agent.skill_runner import DISCOVERY_SCHEMA, run_rf_search

    cand = {"model": "ASL4020", "manufacturer": "Aelius", "url": "http://d/asl4020.pdf"}
    line = '@@CANDIDATE@@ {"model": "ASL4020", "manufacturer": "Aelius", "url": "http://d/asl4020.pdf"}\n'
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(line)]),
        _FakeResultMessage(structured_output={"candidates": [cand]}),
    ]
    # Each rf-verify call (via query) returns that candidate as a match.
    vcaptured: dict = {}
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{**cand, "verdict": "match"}]})],
        vcaptured,
    )

    seen: list = []
    out = asyncio.run(
        run_rf_search(
            "Component type: amplifier | Gain: >= 20 dB",
            on_text=lambda _t: None, on_component=seen.append,
        )
    )

    # Discovery ran the rf-discovery skill with the discovery schema + candidate stream.
    disc = _FakeClient.instances[-1]
    assert disc.options.skills == ["rf-discovery"]
    assert disc.options.kwargs["output_format"] == DISCOVERY_SCHEMA
    assert "@@CANDIDATE@@" in disc.queried
    # The candidate was verified (rf-verify) and streamed to on_component.
    assert [c["model"] for c in seen] == ["ASL4020"]
    assert out == {"components": [{**cand, "verdict": "match"}]}
    assert vcaptured["options"].skills == ["rf-verify"]
    assert "ASL4020" in vcaptured["prompt"]


def test_pipelined_dedupes_repeated_candidates(fake_sdk):
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    dup = '@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n'
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(dup), _Block(dup)]),   # same candidate twice
        _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
    ]
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "match"}]})],
        {},
    )

    seen: list = []
    out = asyncio.run(
        run_rf_search_pipelined("spec", on_text=lambda _t: None, on_component=seen.append)
    )
    assert len(seen) == 1                    # deduped: one verify, one component
    assert len(out["components"]) == 1


def test_pipelined_stop_interrupts_and_does_not_raise(fake_sdk):
    import threading
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    errored = _FakeResultMessage(subtype="interrupted")
    errored.is_error = True
    _FakeClient.messages = [_FakeAssistantMessage([_Block("searching")]), errored]
    fake_sdk.query = _make_query([_FakeResultMessage(structured_output={"components": []})], {})

    stop = threading.Event()
    stop.set()   # already requested -> discovery interrupts on the first message

    meta: dict = {}
    out = asyncio.run(
        run_rf_search_pipelined(
            "spec", on_text=lambda _t: None, on_result=meta.update, stop_event=stop
        )
    )
    disc = _FakeClient.instances[-1]
    assert disc.interrupted is True
    assert meta["stopped"] is True
    assert out == {"components": []}


def test_conductor_emits_events_for_actions_candidates_and_verify(fake_sdk):
    """The event tap surfaces the run's ground truth: discovery's WebFetch, the
    candidate, the Gemini datasheet read (tagged to its verify), verify's kept
    result, the verbatim coverage, and run boundaries with derived counts."""
    from types import SimpleNamespace

    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    cand_line = '@@CANDIDATE@@ {"model": "BLB28", "manufacturer": "BeRex", "url": "u"}\n'
    web_block = SimpleNamespace(id="t1", name="WebFetch", input={"url": "https://everything.rf/x"})
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(cand_line), web_block]),
        _FakeResultMessage(
            subtype="success", result="Coverage: path A ran; 2 vendors.",
            structured_output={"candidates": [{"model": "BLB28", "manufacturer": "BeRex", "url": "u"}]},
        ),
    ]
    # Verify issues a Gemini datasheet read (Bash run_extract) then returns a match.
    ds_block = SimpleNamespace(
        id="t2", name="Bash",
        input={"command": 'python run_extract.py --url "https://d/BLB28.pdf" --params "NF"'},
    )
    fake_sdk.query = _make_query(
        [
            _FakeAssistantMessage([ds_block]),
            _FakeResultMessage(structured_output={"components": [
                {"model": "BLB28", "manufacturer": "BeRex", "url": "u", "verdict": "partial 4/5"}
            ]}),
        ],
        {},
    )

    events: list = []
    asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None, on_event=events.append))

    kinds = [e["kind"] for e in events]
    assert run_log.RUN_STARTED in kinds and run_log.RUN_FINISHED in kinds
    # Discovery's WebFetch captured from the real tool call, not prose.
    assert any(
        e["kind"] == run_log.TOOL_CALL and e["tool"] == "WebFetch"
        and "everything.rf" in e["target"] for e in events
    )
    assert any(e["kind"] == run_log.CANDIDATE_FOUND and e["model"] == "BLB28" for e in events)
    # The Gemini datasheet read, recognized and tagged to its verify agent.
    ds = [e for e in events if e["kind"] == run_log.DATASHEET_READ]
    assert ds and ds[0]["agent_id"] == "verify[BLB28]" and ds[0]["params"] == "NF"
    assert any(e["kind"] == run_log.VERIFY_RESULT and e.get("status") == "kept" for e in events)
    assert any(e["kind"] == run_log.COVERAGE and "path A" in e["text"] for e in events)
    finished = [e for e in events if e["kind"] == run_log.RUN_FINISHED][0]
    assert finished["found"] == 1 and finished["kept"] == 1


def test_conductor_logs_to_disk_only_when_rf_log_on(fake_sdk, monkeypatch, tmp_path):
    """RF_LOG on writes runs/<ts>/events.jsonl + summary.md; off writes nothing.
    Returned components are identical either way."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))

    def _fresh_messages():
        _FakeClient.messages = [
            _FakeAssistantMessage([_Block('@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n')]),
            _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
        ]
        fake_sdk.query = _make_query(
            [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "match"}]})],
            {},
        )

    # OFF (unset): no runs/ directory at all.
    monkeypatch.delenv("RF_LOG", raising=False)
    _fresh_messages()
    out_off = asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None))
    assert not (tmp_path / "runs").exists()

    # ON: a run dir with the events file and the summary.
    monkeypatch.setenv("RF_LOG", "on")
    _fresh_messages()
    out_on = asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None))
    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "events.jsonl").exists()
    assert (run_dirs[0] / "summary.md").exists()

    # Results are unaffected by logging.
    assert out_off == out_on == {"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "match"}]}


def test_pipelined_reports_running_tokens_with_breakdown(fake_sdk):
    """on_tokens ticks as each agent finishes; totals accumulate and split into
    kinds (cache_read counted separately from fresh input/output)."""
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    disc_done = _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]})
    disc_done.usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900}
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block('@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n')]),
        disc_done,
    ]
    vres = _FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "match"}]})
    vres.usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 200}
    fake_sdk.query = _make_query([vres], {})

    ticks: list = []
    asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None, on_tokens=ticks.append))

    assert len(ticks) >= 2                        # discovery + verify each tick once
    assert ticks[0]["tokens"] <= ticks[-1]["tokens"]   # running total only grows
    assert ticks[-1]["tokens"] == 1265            # 1050 (disc) + 215 (verify)
    bd = ticks[-1]["token_breakdown"]
    assert bd["cache_read"] == 1100               # the cheap re-reads, counted apart
    assert bd["input"] == 110 and bd["output"] == 55


# --- RF_SKILL_MODE switch (real vs offline test skills) --------------------


def test_skill_mode_defaults_to_real(monkeypatch):
    from rf_finder.agent.skill_runner import _resolve_skills, _test_mode

    monkeypatch.delenv("RF_SKILL_MODE", raising=False)
    assert _test_mode() is False
    disc, _dt, verify, _vt = _resolve_skills()
    assert disc == "rf-discovery"
    assert verify == "rf-verify"


def test_skill_mode_test_selects_offline_skills_and_no_web_tools(monkeypatch):
    from rf_finder.agent.skill_runner import _resolve_skills, _test_mode

    monkeypatch.setenv("RF_SKILL_MODE", "test")
    assert _test_mode() is True
    disc, disc_tools, verify, verify_tools = _resolve_skills()
    assert disc == "rf-discovery-test"
    assert verify == "rf-verify-test"
    # The hard offline guarantee: web/Bash tools are physically withheld.
    for tool in ("WebSearch", "WebFetch", "Bash"):
        assert tool not in disc_tools
        assert tool not in verify_tools


def test_skill_mode_tolerates_case_and_whitespace(monkeypatch):
    from rf_finder.agent.skill_runner import _test_mode

    monkeypatch.setenv("RF_SKILL_MODE", "  Test ")
    assert _test_mode() is True
    monkeypatch.setenv("RF_SKILL_MODE", "real")
    assert _test_mode() is False


# --- RF_LOG switch (run logging on/off) ------------------------------------


def test_logging_enabled_only_for_on_token(monkeypatch):
    from rf_finder.agent.skill_runner import _logging_enabled

    monkeypatch.setenv("RF_LOG", "on")
    assert _logging_enabled() is True
    monkeypatch.setenv("RF_LOG", "  ON ")   # case/whitespace tolerant
    assert _logging_enabled() is True


def test_logging_disabled_when_unset_empty_or_unknown(monkeypatch):
    from rf_finder.agent.skill_runner import _logging_enabled

    monkeypatch.delenv("RF_LOG", raising=False)
    assert _logging_enabled() is False        # unset -> off
    monkeypatch.setenv("RF_LOG", "")
    assert _logging_enabled() is False        # empty -> off
    monkeypatch.setenv("RF_LOG", "off")
    assert _logging_enabled() is False
    monkeypatch.setenv("RF_LOG", "true")
    assert _logging_enabled() is False        # unknown token -> off (never by accident)


def test_pipelined_uses_test_skills_when_mode_test(fake_sdk, monkeypatch):
    """End-to-end at the conductor level: in test mode the discovery client and
    the verify call both load the *-test skills, with no web tools."""
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setenv("RF_SKILL_MODE", "test")
    line = '@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n'
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(line)]),
        _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
    ]
    vcaptured: dict = {}
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "match"}]})],
        vcaptured,
    )

    asyncio.run(run_rf_search_pipelined("spec", on_text=lambda _t: None))

    disc = _FakeClient.instances[-1]
    assert disc.options.skills == ["rf-discovery-test"]
    assert "WebSearch" not in disc.options.allowed_tools
    assert "WebFetch" not in disc.options.allowed_tools
    assert vcaptured["options"].skills == ["rf-verify-test"]
    assert "Bash" not in vcaptured["options"].allowed_tools
    # The prompt names the offline skill, not the real one.
    assert "rf-discovery-test" in disc.queried
    assert "rf-verify-test" in vcaptured["prompt"]


# --- run metadata (Feature 2) + error surfacing (Feature 1) ----------------


def test_on_result_receives_meta_with_summed_tokens(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    m = _FakeResultMessage(subtype="success", structured_output={"components": []})
    m.num_turns = 4
    m.usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 10}
    fake_sdk.query = _make_query([m], {})

    captured: dict = {}
    asyncio.run(
        run_agent_skill(
            "p", skills=[], allowed_tools=[],
            output_format={"type": "json_schema", "schema": {}},
            on_text=lambda _t: None, on_result=captured.update,
        )
    )
    assert captured["is_error"] is False
    assert captured["num_turns"] == 4
    assert captured["tokens"] == 160


def test_errored_run_raises_with_status_code(fake_sdk):
    from rf_finder.agent.skill_runner import run_agent_skill

    m = _FakeResultMessage(subtype="error", structured_output={"components": []})
    m.is_error = True
    m.api_error_status = 429
    m.num_turns = 7
    fake_sdk.query = _make_query([m], {})

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(
            run_agent_skill(
                "p", skills=[], allowed_tools=[],
                output_format={"type": "json_schema", "schema": {}},
                on_text=lambda _t: None,
            )
        )
    assert "429" in str(excinfo.value)


# --- RF_RESUME: continue from prior-run logs -------------------------------


def _write_prior_run(runs_base, name, events):
    """Create ``runs_base/<name>/events.jsonl`` from a list of event dicts."""
    run_dir = runs_base / name
    run_dir.mkdir(parents=True)
    with open(run_dir / "events.jsonl", "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def test_resume_off_runs_discovery_even_with_matching_log(fake_sdk, monkeypatch, tmp_path):
    """RF_RESUME unset (default): a matching prior log is ignored; discovery runs."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("RF_RESUME", raising=False)
    _write_prior_run(tmp_path / "runs", "20260101_000000_000000", [
        {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": "SPEC"},
        {"kind": run_log.AGENT_FINISHED, "agent_id": "discovery", "is_error": False},
        {"kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "X", "url": "u"},
        {"kind": run_log.VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept",
         "model": "M1", "verdict": "from-log", "outcome": run_log.OUTCOME_KEPT},
    ])
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block('@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n')]),
        _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
    ]
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "fresh"}]})],
        {},
    )

    out = asyncio.run(run_rf_search_pipelined("SPEC", on_text=lambda _t: None))
    assert _FakeClient.instances                       # discovery client was opened
    assert out["components"][0]["verdict"] == "fresh"  # verified fresh, not reused


def test_resume_skips_clean_discovery_and_passes_kept_through(fake_sdk, monkeypatch, tmp_path):
    """RF_RESUME on + prior clean discovery: discovery is skipped entirely and the
    prior kept candidate is passed straight through without re-verifying."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("RF_RESUME", "on")
    _write_prior_run(tmp_path / "runs", "20260101_000000_000000", [
        {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": "SPEC"},
        {"kind": run_log.AGENT_FINISHED, "agent_id": "discovery", "is_error": False},
        {"kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "BeRex", "url": "u1"},
        {"kind": run_log.VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept",
         "model": "M1", "verdict": "from-log", "outcome": run_log.OUTCOME_KEPT},
    ])
    # If verify or discovery were invoked, this would blow up the run.
    def _boom(*a, **k):
        raise AssertionError("no agent call expected on a fully-reused run")
    fake_sdk.query = _boom
    _FakeClient.messages = []

    seen: list = []
    out = asyncio.run(run_rf_search_pipelined("SPEC", on_text=lambda _t: None, on_component=seen.append))

    assert _FakeClient.instances == []                 # discovery skipped: no client opened
    assert out["components"] == [{"model": "M1", "manufacturer": "BeRex", "url": "u1", "verdict": "from-log"}]
    assert [c["model"] for c in seen] == ["M1"]        # reused kept reached on_component


def test_resume_reruns_discovery_but_does_not_repeat_settled_verify(fake_sdk, monkeypatch, tmp_path):
    """RF_RESUME on + prior discovery INCOMPLETE: discovery re-runs, but a candidate
    already kept is not re-verified — only a newly-surfaced candidate is."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("RF_RESUME", "on")
    _write_prior_run(tmp_path / "runs", "20260101_000000_000000", [
        {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": "SPEC"},
        {"kind": run_log.AGENT_FINISHED, "agent_id": "discovery", "is_error": True},  # incomplete
        {"kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "X", "url": "u1"},
        {"kind": run_log.VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept",
         "model": "M1", "verdict": "from-log", "outcome": run_log.OUTCOME_KEPT},
    ])
    # Discovery re-runs and re-streams M1 (settled) plus a brand-new M2.
    disc_text = (
        '@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u1"}\n'
        '@@CANDIDATE@@ {"model": "M2", "manufacturer": "X", "url": "u2"}\n'
    )
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block(disc_text)]),
        _FakeResultMessage(structured_output={"candidates": [
            {"model": "M1", "manufacturer": "X", "url": "u1"},
            {"model": "M2", "manufacturer": "X", "url": "u2"},
        ]}),
    ]
    # Count verify calls and record which candidate each was for.
    calls = {"n": 0, "prompts": []}

    async def _q(*, prompt, options):
        calls["n"] += 1
        calls["prompts"].append(prompt)
        yield _FakeResultMessage(structured_output={"components": [
            {"model": "M2", "manufacturer": "X", "url": "u2", "verdict": "fresh"}
        ]})

    fake_sdk.query = _q

    out = asyncio.run(run_rf_search_pipelined("SPEC", on_text=lambda _t: None))

    assert _FakeClient.instances                        # discovery DID re-run
    assert calls["n"] == 1                              # only ONE verify — M1 was not repeated
    assert "M2" in calls["prompts"][0] and "M1" not in calls["prompts"][0]
    models = {c["model"]: c["verdict"] for c in out["components"]}
    assert models == {"M1": "from-log", "M2": "fresh"}  # M1 reused, M2 fresh


def test_resume_reverifies_failed_infra_candidate(fake_sdk, monkeypatch, tmp_path):
    """RF_RESUME on + prior clean discovery, but the candidate's prior verify was a
    failed_infra (dead Gemini): discovery is skipped, yet the candidate IS
    re-verified rather than treated as settled."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("RF_RESUME", "on")
    _write_prior_run(tmp_path / "runs", "20260101_000000_000000", [
        {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": "SPEC"},
        {"kind": run_log.AGENT_FINISHED, "agent_id": "discovery", "is_error": False},
        {"kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "X", "url": "u1"},
        {"kind": run_log.VERIFY_RESULT, "agent_id": "verify[M1]", "status": "rejected",
         "model": "M1", "reason": "insufficient verification: Gemini not available",
         "outcome": run_log.OUTCOME_FAILED_INFRA},
    ])
    _FakeClient.messages = []      # discovery must be skipped (clean prior)
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u1", "verdict": "now-verified"}]})],
        {},
    )

    out = asyncio.run(run_rf_search_pipelined("SPEC", on_text=lambda _t: None))

    assert _FakeClient.instances == []                  # discovery skipped
    assert out["components"] == [{"model": "M1", "manufacturer": "X", "url": "u1", "verdict": "now-verified"}]


def test_resume_on_with_no_matching_log_runs_fresh(fake_sdk, monkeypatch, tmp_path):
    """RF_RESUME on but nothing matches this query: run proceeds fresh, no error."""
    import rf_finder.agent.skill_runner as sr
    from rf_finder.agent import run_log
    from rf_finder.agent.skill_runner import run_rf_search_pipelined

    monkeypatch.setattr(sr, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("RF_RESUME", "on")
    _write_prior_run(tmp_path / "runs", "20260101_000000_000000", [
        {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": "A DIFFERENT SPEC"},
        {"kind": run_log.AGENT_FINISHED, "agent_id": "discovery", "is_error": False},
    ])
    _FakeClient.messages = [
        _FakeAssistantMessage([_Block('@@CANDIDATE@@ {"model": "M1", "manufacturer": "X", "url": "u"}\n')]),
        _FakeResultMessage(structured_output={"candidates": [{"model": "M1", "manufacturer": "X", "url": "u"}]}),
    ]
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": [{"model": "M1", "manufacturer": "X", "url": "u", "verdict": "fresh"}]})],
        {},
    )

    out = asyncio.run(run_rf_search_pipelined("SPEC", on_text=lambda _t: None))
    assert _FakeClient.instances                        # discovery ran fresh
    assert out["components"][0]["verdict"] == "fresh"
