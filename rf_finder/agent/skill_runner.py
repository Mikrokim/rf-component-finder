"""Claude Agent SDK plumbing for the RF finder.

Ported from the proven learning-project wrapper. ``run_agent_skill`` is the one
place that talks to Claude via the Agent SDK. ``run_rf_search`` wires the real
``rf-skill-json-output`` skill — the GUI's "AI Search" button calls it.

The SDK is imported lazily inside ``run_agent_skill`` so importing this module
(and the GUI) never fails when the optional ``claude-agent-sdk`` dependency is
absent — a missing SDK surfaces only when a run is actually attempted.
"""

from __future__ import annotations

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


async def run_agent_skill(
    prompt: str,
    *,
    skills: list[str],
    allowed_tools: list[str],
    model: str = "opus",
    on_text: Callable[[str], None] = print,
    output_format: dict[str, Any] | None = None,
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

    return structured if output_format is not None else result_text


async def run_rf_search(
    spec_text: str,
    *,
    on_text: Callable[[str], None] = print,
) -> Any:
    """Real RF search: hand the user's form parameters to the
    ``rf-skill-json-output`` skill and return the components it produces.

    Drives ``run_agent_skill`` with the ``COMPONENT_SCHEMA`` structured output.
    ``Bash`` is allowed so the skill can
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
        f"Search parameters (separated by ' | '):\n{spec_text}"
    )
    return await run_agent_skill(
        prompt,
        skills=["rf-skill-json-output"],
        allowed_tools=["Skill", "Bash", "Read", "WebSearch", "WebFetch", "Glob", "Grep"],
        model="opus",
        on_text=on_text,
        output_format=COMPONENT_SCHEMA,
    )
