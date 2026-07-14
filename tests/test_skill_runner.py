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


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a fake ``claude_agent_sdk`` module; per-test set ``.query``."""
    mod = types.ModuleType("claude_agent_sdk")
    mod.AssistantMessage = _FakeAssistantMessage
    mod.ResultMessage = _FakeResultMessage
    mod.ClaudeAgentOptions = _FakeOptions
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


# --- run_rf_search wiring (the real skill) ---------------------------------


def test_run_rf_search_uses_real_skill_and_schema(fake_sdk):
    from rf_finder.agent.skill_runner import COMPONENT_SCHEMA, run_rf_search

    captured = {}
    fake_sdk.query = _make_query(
        [_FakeResultMessage(structured_output={"components": []})], captured
    )

    asyncio.run(
        run_rf_search(
            "Component type: amplifier | Gain: >= 20 dB", on_text=lambda _t: None
        )
    )

    opts = captured["options"]
    assert opts.skills == ["rf-skill-json-output"]
    assert opts.model == "opus"
    # Bash MUST be allowed so the skill can run its OWN bundled tools
    # (tools/run_extract.py -> Gemini datasheet extraction).
    assert "Bash" in opts.allowed_tools
    assert opts.kwargs["output_format"] == COMPONENT_SCHEMA
    assert "amplifier" in captured["prompt"]


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
