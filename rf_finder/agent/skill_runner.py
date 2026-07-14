"""Claude Agent SDK plumbing for the RF finder.

Ported from the proven learning-project wrapper. ``run_agent_skill`` is the one
place that talks to Claude via the Agent SDK. ``run_rf_search`` wires the real
``rf-skill-json-output`` skill — the GUI's "AI Search" button calls it.

The SDK is imported lazily inside ``run_agent_skill`` so importing this module
(and the GUI) never fails when the optional ``claude-agent-sdk`` dependency is
absent — a missing SDK surfaces only when a run is actually attempted.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

# Repo root: .../rf-component-finder/  (this module is at rf_finder/agent/).
# Claude runs with this as cwd so setting_sources can discover .claude/skills/.
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Best-effort .env load for the ANTHROPIC_API_KEY path (optional dependency).
# Not needed when logged into Claude Code — the SDK uses that login.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except Exception:
    pass


#: Structured-output schema: the skill returns a list of components. Passing
#: this as ``output_format`` is what makes the SDK populate
#: ``ResultMessage.structured_output`` (instead of returning free text).
COMPONENT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "manufacturer": {"type": "string"},
                        "url": {"type": "string"},
                        "verdict": {"type": "string"},
                    },
                    "required": ["model", "manufacturer", "url"],
                },
            }
        },
        "required": ["components"],
    },
}


def _sum_tokens(usage: Any) -> int | None:
    """Best-effort total token count from a ``ResultMessage.usage`` dict.

    Sums the integer values whose key mentions "token" (input/output/cache), so
    it is robust to the exact key set. Returns ``None`` when nothing is found.
    """
    if not isinstance(usage, dict):
        return None
    total = 0
    found = False
    for key, value in usage.items():
        if isinstance(value, int) and "token" in key.lower():
            total += value
            found = True
    return total if found else None


def _run_error_message(meta: dict[str, Any]) -> str:
    """A clear one-line reason a run did not complete (for the error popup)."""
    bits: list[str] = []
    if meta.get("api_error_status"):
        bits.append(f"HTTP {meta['api_error_status']}")
    subtype = meta.get("subtype")
    if subtype and subtype != "success":
        bits.append(str(subtype))
    if meta.get("stop_reason"):
        bits.append(f"stop_reason={meta['stop_reason']}")
    detail = ", ".join(bits) if bits else "unknown error"
    tail: list[str] = []
    if meta.get("num_turns") is not None:
        tail.append(f"{meta['num_turns']} turns")
    if meta.get("tokens") is not None:
        tail.append(f"{meta['tokens']:,} tokens")
    tail_s = f" ({', '.join(tail)})" if tail else ""
    return f"AI Search did not complete: {detail}{tail_s}."


async def run_agent_skill(
    prompt: str,
    *,
    skills: list[str],
    allowed_tools: list[str],
    model: str = "opus",
    on_text: Callable[[str], None] = print,
    output_format: dict[str, Any] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    """The SDK connection itself — the one place that talks to Claude.

    Hands ``prompt`` to Claude via the Agent SDK, loads the given ``skills``,
    permits the given ``allowed_tools``, streams progress to ``on_text``
    (default ``print``), and — when ``output_format`` (a JSON schema) is given —
    asks for a structured result.

    Returns the run's ``structured_output`` when a schema was requested, else
    the final answer text (``result``). It knows only skill *names*, *allowed
    tools*, and an optional schema — never a skill's internal steps — so any
    finished Skill drops in unchanged.

    Run metadata (completion ``subtype``, ``is_error``, ``api_error_status``,
    ``num_turns``, and a summed ``tokens`` count) is passed to ``on_result`` when
    given. A run that ended in error (``is_error``) raises ``RuntimeError`` with
    a one-line reason, so callers surface it instead of returning a partial
    result silently.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )

    options_kwargs: dict[str, Any] = dict(
        cwd=PROJECT_ROOT,
        setting_sources=["user", "project"],  # user = companion skills, project = local
        skills=skills,
        allowed_tools=allowed_tools,
        model=model,
        permission_mode="acceptEdits",
    )
    if output_format is not None:
        options_kwargs["output_format"] = output_format
    options = ClaudeAgentOptions(**options_kwargs)

    result_text: str | None = None
    structured: Any = None
    meta: dict[str, Any] = {}
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                text = getattr(block, "text", None)
                if text:
                    on_text(text)  # live progress for the caller
        elif isinstance(message, ResultMessage):
            on_text(f"\n[done: {message.subtype}]")
            result_text = message.result
            structured = message.structured_output
            meta = {
                "subtype": message.subtype,
                "is_error": bool(getattr(message, "is_error", False)),
                "api_error_status": getattr(message, "api_error_status", None),
                "stop_reason": getattr(message, "stop_reason", None),
                "num_turns": getattr(message, "num_turns", None),
                "tokens": _sum_tokens(getattr(message, "usage", None)),
            }

    if on_result is not None:
        on_result(meta)

    # A failed/truncated run (rate limit, session boundary, API error) must not
    # return a partial result silently — raise so the caller shows it (popup).
    if meta.get("is_error"):
        raise RuntimeError(_run_error_message(meta))

    return structured if output_format is not None else result_text


_RESULT_MARKER = "@@RESULT@@"


def _emit_components(buffer: str, on_component: Callable[[dict[str, Any]], None]) -> str:
    """Pull ``@@RESULT@@ {json}`` lines out of streamed text as they complete.

    The skill prints one such line per confirmed component *during* the run.
    Streamed text arrives in arbitrary chunks, so ``buffer`` accumulates it and
    only *complete* lines (those followed by a newline) are parsed; the trailing
    partial line is returned to be completed by the next chunk. Each parsed
    component object is handed to ``on_component``. A malformed line is skipped
    (the authoritative full list still arrives in the final structured output).
    """
    *lines, remainder = buffer.split("\n")
    for line in lines:
        line = line.strip()
        if not line.startswith(_RESULT_MARKER):
            continue
        payload = line[len(_RESULT_MARKER):].strip()
        try:
            component = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(component, dict):
            on_component(component)
    return remainder


async def run_agent_skill_streaming(
    prompt: str,
    *,
    skills: list[str],
    allowed_tools: list[str],
    model: str = "opus",
    on_text: Callable[[str], None] = print,
    output_format: dict[str, Any] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_component: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
) -> Any:
    """Like ``run_agent_skill``, but over ``ClaudeSDKClient`` so the run can be
    interrupted mid-flight and each result surfaced as it is found.

    Two additions over ``run_agent_skill``:

    - ``on_component`` — called with each component the skill emits *during* the
      run (parsed from ``@@RESULT@@`` lines in the streamed text), so a caller
      can show results live instead of waiting for the final list.
    - ``stop_event`` — a ``threading.Event``-like object; when set (e.g. by a GUI
      "Stop" button), the run is ``interrupt()``-ed and ends early. A user stop is
      NOT an error, so it does not raise — whatever was collected is returned.

    Otherwise identical: streams text to ``on_text``, reports run metadata to
    ``on_result``, returns ``structured_output`` (schema) / ``result`` (text), and
    raises on a genuine error (but never on a user stop).
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
    )

    options_kwargs: dict[str, Any] = dict(
        cwd=PROJECT_ROOT,
        setting_sources=["user", "project"],
        skills=skills,
        allowed_tools=allowed_tools,
        model=model,
        permission_mode="acceptEdits",
    )
    if output_format is not None:
        options_kwargs["output_format"] = output_format
    options = ClaudeAgentOptions(**options_kwargs)

    result_text: str | None = None
    structured: Any = None
    meta: dict[str, Any] = {}
    buffer = ""
    stopped = False

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if stop_event is not None and stop_event.is_set():
                stopped = True
                await client.interrupt()
                break
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        on_text(text)  # live progress for the caller
                        if on_component is not None:
                            buffer = _emit_components(buffer + text, on_component)
            elif isinstance(message, ResultMessage):
                on_text(f"\n[done: {message.subtype}]")
                result_text = message.result
                structured = message.structured_output
                meta = {
                    "subtype": message.subtype,
                    "is_error": bool(getattr(message, "is_error", False)),
                    "api_error_status": getattr(message, "api_error_status", None),
                    "stop_reason": getattr(message, "stop_reason", None),
                    "num_turns": getattr(message, "num_turns", None),
                    "tokens": _sum_tokens(getattr(message, "usage", None)),
                }

    meta["stopped"] = stopped
    if on_result is not None:
        on_result(meta)

    # A user stop is expected, not a failure — only a real error raises.
    if meta.get("is_error") and not stopped:
        raise RuntimeError(_run_error_message(meta))

    return structured if output_format is not None else result_text


async def run_rf_search(
    spec_text: str,
    *,
    on_text: Callable[[str], None] = print,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_component: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
) -> Any:
    """Real RF search: hand the user's form parameters to the
    ``rf-skill-json-output`` skill and return the components it produces.

    Drives ``run_agent_skill_streaming`` with the ``COMPONENT_SCHEMA`` structured
    output, so the run can be stopped mid-flight (``stop_event``) and each result
    shown as it is found (``on_component``). ``Bash`` is allowed so the skill can
    run its OWN bundled tools (``tools/run_extract.py`` -> Gemini datasheet
    extraction); ``WebSearch``/``WebFetch`` drive the discovery paths; ``Read``
    loads the skill's reference modules; ``Skill`` lets Claude invoke the skill.
    Returns the structured result (a dict with a ``components`` list).
    """
    prompt = (
        "Use the rf-skill-json-output skill to find RF components matching the "
        "parameters below. You MUST invoke the skill and return exactly the "
        "components it produces — do NOT invent, add, remove, or modify "
        "components, and do NOT answer from your own knowledge. If the skill "
        "produces nothing, return an empty list.\n\n"
        "As the skill confirms each matching component, emit it immediately on "
        "its own line as `@@RESULT@@ {json}` (the component object), so results "
        "can be shown live — then still return the full list at the end.\n\n"
        f"Search parameters (separated by ' | '):\n{spec_text}"
    )
    return await run_agent_skill_streaming(
        prompt,
        skills=["rf-skill-json-output"],
        allowed_tools=["Skill", "Bash", "Read", "WebSearch", "WebFetch", "Glob", "Grep"],
        model="opus",
        on_text=on_text,
        output_format=COMPONENT_SCHEMA,
        on_result=on_result,
        on_component=on_component,
        stop_event=stop_event,
    )
