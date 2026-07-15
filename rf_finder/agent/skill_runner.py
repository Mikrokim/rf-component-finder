"""Claude Agent SDK plumbing for the RF finder.

Ported from the proven learning-project wrapper. ``run_agent_skill`` is the one
place that talks to Claude via the Agent SDK. ``run_rf_search`` wires the real
``rf-skill-json-output`` skill — the GUI's "AI Search" button calls it.

The SDK is imported lazily inside ``run_agent_skill`` so importing this module
(and the GUI) never fails when the optional ``claude-agent-sdk`` dependency is
absent — a missing SDK surfaces only when a run is actually attempted.
"""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Pipelined conductor: rf-discovery (streaming) -> one rf-verify per candidate
# ---------------------------------------------------------------------------

DISCOVERY_SKILL = "rf-discovery"
VERIFY_SKILL = "rf-verify"

# Discovery finds/screens parts (no datasheet reading) -> no Bash needed.
_DISCOVERY_TOOLS = ["Skill", "Read", "WebSearch", "WebFetch", "Glob", "Grep"]
# Verify reads ONE datasheet via its bundled tools -> needs Bash (+ web for
# alternative datasheet sources when the primary is blocked).
_VERIFY_TOOLS = ["Skill", "Bash", "Read", "WebSearch", "WebFetch"]

#: Discovery's final structured output — the complete deduped candidate list,
#: a safety net beside the live ``@@CANDIDATE@@`` stream.
DISCOVERY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "manufacturer": {"type": "string"},
                        "url": {"type": "string"},
                    },
                    "required": ["model"],
                },
            }
        },
        "required": ["candidates"],
    },
}

_CANDIDATE_MARKER = "@@CANDIDATE@@"


def _extract_candidates(buffer: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull ``@@CANDIDATE@@ {json}`` lines out of streamed discovery text.

    Buffered line parsing: only complete lines (those followed by a newline) are
    parsed; the trailing partial line is returned to be completed by the next
    chunk. Returns ``(remainder, [candidate, ...])``.
    """
    *lines, remainder = buffer.split("\n")
    found: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith(_CANDIDATE_MARKER):
            continue
        payload = line[len(_CANDIDATE_MARKER):].strip()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("model"):
            found.append(obj)
    return remainder, found


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    """Dedup key for a candidate: (model, manufacturer), case-insensitive."""
    return (
        str(candidate.get("model", "")).strip().lower(),
        str(candidate.get("manufacturer", "")).strip().lower(),
    )


def _discovery_prompt(spec_text: str) -> str:
    return (
        "Use the rf-discovery skill to find RF components matching the parameters "
        "below. Emit each surviving candidate immediately on its own line as "
        "`@@CANDIDATE@@ {json}` (model, manufacturer, url), and also return the "
        "full candidates list at the end. Do NOT read datasheets or decide final "
        "matches — that happens downstream.\n\n"
        f"Search parameters (separated by ' | '):\n{spec_text}"
    )


def _verify_prompt(candidate: dict[str, Any], spec_text: str) -> str:
    return (
        "Use the rf-verify skill to verify this ONE candidate against the spec. "
        "Return exactly the skill's result — do NOT invent, add, or modify it. If "
        "it does not qualify, return an empty components list.\n\n"
        f"Candidate: model={candidate.get('model', '')}, "
        f"manufacturer={candidate.get('manufacturer', '')}, "
        f"url={candidate.get('url', '')}\n"
        f"Spec (parameters, separated by ' | '):\n{spec_text}"
    )


async def run_rf_search_pipelined(
    spec_text: str,
    *,
    on_text: Callable[[str], None] = print,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_component: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
    max_concurrency: int = 4,
) -> Any:
    """Conductor: run ``rf-discovery`` (streaming) and fire one ``rf-verify`` run
    per candidate the instant it surfaces.

    This is the hard guarantee that each component is handled independently: every
    candidate becomes its OWN ``rf-verify`` agent call, so a match reaches
    ``on_component`` the moment its verify finishes — no candidate waits for the
    others. The code (not the model) enforces the per-candidate pipeline.

    - Discovery streams ``@@CANDIDATE@@`` lines; each new (deduped) candidate spawns
      a verify task, bounded by ``max_concurrency``.
    - ``stop_event`` interrupts discovery and cancels pending verifies (a user stop
      is not an error).
    - Token/turn totals are summed across discovery + every verify call.
    Returns ``{"components": [...]}`` — the qualifying parts, same shape as before.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
    )

    seen: set[tuple[str, str]] = set()
    tasks: list[asyncio.Task] = []
    components: list[dict[str, Any]] = []
    totals = {"tokens": 0, "num_turns": 0}
    sem = asyncio.Semaphore(max(1, max_concurrency))
    stopped = False

    def _accumulate(m: dict[str, Any]) -> None:
        totals["tokens"] += (m.get("tokens") or 0)
        totals["num_turns"] += (m.get("num_turns") or 0)

    async def _verify(candidate: dict[str, Any]) -> None:
        async with sem:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                result = await run_agent_skill(
                    _verify_prompt(candidate, spec_text),
                    skills=[VERIFY_SKILL],
                    allowed_tools=_VERIFY_TOOLS,
                    model="opus",
                    on_text=on_text,
                    output_format=COMPONENT_SCHEMA,
                    on_result=_accumulate,
                )
            except Exception:
                # One failed verify (error/rate-limit on that call) must not kill
                # the whole pipeline; its candidate is simply dropped.
                return
            for comp in (result or {}).get("components", []):
                components.append(comp)
                if on_component is not None:
                    on_component(comp)

    def _spawn(candidate: dict[str, Any]) -> None:
        key = _candidate_key(candidate)
        if key in seen:
            return
        seen.add(key)
        tasks.append(asyncio.create_task(_verify(candidate)))

    options = ClaudeAgentOptions(
        cwd=PROJECT_ROOT,
        setting_sources=["user", "project"],
        skills=[DISCOVERY_SKILL],
        allowed_tools=_DISCOVERY_TOOLS,
        model="opus",
        permission_mode="acceptEdits",
        output_format=DISCOVERY_SCHEMA,
    )

    buffer = ""
    disc_meta: dict[str, Any] = {}
    disc_candidates: list[dict[str, Any]] = []

    async with ClaudeSDKClient(options=options) as client:
        await client.query(_discovery_prompt(spec_text))
        async for message in client.receive_response():
            if stop_event is not None and stop_event.is_set():
                stopped = True
                await client.interrupt()
                break
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    text = getattr(block, "text", None)
                    if text:
                        on_text(text)
                        buffer, fresh = _extract_candidates(buffer + text)
                        for cand in fresh:
                            _spawn(cand)   # verify starts NOW, mid-discovery
            elif isinstance(message, ResultMessage):
                on_text(f"\n[discovery done: {message.subtype}]")
                disc_meta = {
                    "subtype": message.subtype,
                    "is_error": bool(getattr(message, "is_error", False)),
                    "api_error_status": getattr(message, "api_error_status", None),
                    "stop_reason": getattr(message, "stop_reason", None),
                    "num_turns": getattr(message, "num_turns", None),
                    "tokens": _sum_tokens(getattr(message, "usage", None)),
                }
                _accumulate(disc_meta)
                so = getattr(message, "structured_output", None)
                if isinstance(so, dict):
                    disc_candidates = so.get("candidates") or []

    # Safety net: verify any final-list candidate discovery didn't stream (unless
    # the user stopped — then don't start new work).
    if not stopped:
        for cand in disc_candidates:
            _spawn(cand)

    if stopped:
        for task in tasks:
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    meta = {
        "subtype": disc_meta.get("subtype", "success"),
        "is_error": bool(disc_meta.get("is_error")) and not stopped,
        "num_turns": totals["num_turns"],
        "tokens": totals["tokens"],
        "stopped": stopped,
    }
    if on_result is not None:
        on_result(meta)

    # A genuine discovery failure (rate limit / session boundary) surfaces; a user
    # stop does not. Verify-call failures were swallowed per-candidate above.
    if disc_meta.get("is_error") and not stopped:
        raise RuntimeError(_run_error_message(disc_meta))

    return {"components": components}


async def run_rf_search(
    spec_text: str,
    *,
    on_text: Callable[[str], None] = print,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_component: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
) -> Any:
    """Real RF search (the GUI's "AI Search" entry point).

    Delegates to the pipelined conductor ``run_rf_search_pipelined``: ``rf-discovery``
    streams candidates and one ``rf-verify`` runs per candidate, so each component
    is verified independently the moment it is found and reaches ``on_component``
    without waiting for the rest. ``stop_event`` interrupts the run early.
    Returns ``{"components": [...]}``.
    """
    return await run_rf_search_pipelined(
        spec_text,
        on_text=on_text,
        on_result=on_result,
        on_component=on_component,
        stop_event=stop_event,
    )
