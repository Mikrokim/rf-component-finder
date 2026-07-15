"""Headless tests for the Claude Agent SDK wrapper (``rf_finder.agent``).

The SDK is mocked — a fake ``claude_agent_sdk`` module is installed in
``sys.modules`` so ``run_agent_skill`` (which imports it lazily) picks up our
stand-ins. No network, no real model call, no Tk. These lock down the option
building, the structured-vs-text return contract, the ``on_text`` streaming, and
the ``run_rf_search`` configuration.
"""

from __future__ import annotations

import asyncio
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
    """Keep tests independent of the repo ``.env``: default to real mode unless a
    test sets ``RF_SKILL_MODE`` itself. (The app's .env sets it to ``test``, which
    would otherwise leak into every test here.)"""
    monkeypatch.delenv("RF_SKILL_MODE", raising=False)


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
