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

from rf_finder.agent import resume as resume_mod
from rf_finder.agent import run_log
from rf_finder.agent.run_log import block_to_event, make_run_logger

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
            },
            # Optional: a part this verify DROPPED, with a structured reason, so a
            # rejection is logged with its cause instead of vanishing. Populated by
            # rf-verify's fenced reject block; absent-and-empty is fine (an empty
            # components list is still recorded as a reason-less rejection).
            "rejected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "param": {"type": "string"},
                        "found": {"type": ["string", "number", "null"]},
                        "required": {"type": ["string", "number", "null"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["model", "reason"],
                },
            },
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


#: The four token *kinds*, cheapest last. They cost very different amounts:
#: ``cache_read`` is ~10% of ``input`` price, so a big total is mostly the cheap
#: cached re-reads of the (deliberately large) skill files across many turns.
_TOKEN_KINDS = ("input", "output", "cache_read", "cache_write")


def _token_breakdown(usage: Any) -> dict[str, int]:
    """Split a ``usage`` dict into the four token kinds (``_TOKEN_KINDS``).

    ``input`` = fresh, full-price input; ``output`` = generated tokens;
    ``cache_read`` = context re-read from the prompt cache (~1/10 price);
    ``cache_write`` = one-time cost of populating the cache. Their sum equals
    ``_sum_tokens`` — this just says *what* those tokens were.
    """
    b = {k: 0 for k in _TOKEN_KINDS}
    if not isinstance(usage, dict):
        return b
    for key, value in usage.items():
        if not isinstance(value, int):
            continue
        k = key.lower()
        if "cache_read" in k:
            b["cache_read"] += value
        elif "cache_creation" in k or "cache_write" in k:
            b["cache_write"] += value
        elif k == "input_tokens":
            b["input"] += value
        elif k == "output_tokens":
            b["output"] += value
    return b


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
    on_event: Callable[[dict[str, Any]], None] | None = None,
    agent_id: str = "agent",
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
                    continue
                # Non-text blocks (tool use / result) are the run's ground-truth
                # actions — capture them as events when a sink is attached.
                if on_event is not None:
                    ev = block_to_event(block, agent_id)
                    if ev is not None:
                        on_event(ev)
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
                "token_breakdown": _token_breakdown(getattr(message, "usage", None)),
            }

    if on_event is not None:
        on_event({
            "kind": run_log.AGENT_FINISHED,
            "agent_id": agent_id,
            "subtype": meta.get("subtype"),
            "is_error": meta.get("is_error"),
            "num_turns": meta.get("num_turns"),
            "tokens": meta.get("tokens"),
        })

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

# --- Test mode -------------------------------------------------------------
# ``RF_SKILL_MODE=test`` swaps in local-JSON copies of the skills that run the
# SAME workflow against a fixed mock dataset instead of the web + Gemini — for
# cheap, offline end-to-end checks of the whole pipeline (see the *-test skills
# and mockdata/). Default ``real`` runs the live skills. The GUI/conductor are
# unchanged; only the skill *names* and *allowed tools* differ.
DISCOVERY_SKILL_TEST = "rf-discovery-test"
VERIFY_SKILL_TEST = "rf-verify-test"

# Test tools: local JSON only. No WebSearch/WebFetch/Bash, so an external call
# is physically impossible even if the skill instructions were ignored — a hard
# guarantee the test spends no web/Gemini tokens.
_DISCOVERY_TOOLS_TEST = ["Skill", "Read", "Glob", "Grep"]
_VERIFY_TOOLS_TEST = ["Skill", "Read"]


def _test_mode() -> bool:
    """True when ``RF_SKILL_MODE`` selects the offline test skills."""
    return os.environ.get("RF_SKILL_MODE", "real").strip().lower() == "test"


def _logging_enabled() -> bool:
    """True when ``RF_LOG`` turns on AI Search run logging.

    Mirrors ``_test_mode()``: read once from the environment (loaded from
    ``.env``), tolerant of case/whitespace. Only the explicit ``on`` token
    enables logging; unset, empty, or anything unknown is off — so logging never
    turns itself on by accident.
    """
    return os.environ.get("RF_LOG", "").strip().lower() == "on"


def _resume_enabled() -> bool:
    """True when ``RF_RESUME`` turns on continuation from prior-run logs.

    Independent of ``RF_LOG`` (which gates *writing*): this gates only *reading*
    the last runs to continue a re-run of the same query. Resolved exactly like
    ``_logging_enabled`` — only the explicit ``on`` token enables it; unset,
    empty, or anything unknown is off, so resume never turns itself on by
    accident. When on but no prior run matches, the conductor simply runs fresh.
    """
    return os.environ.get("RF_RESUME", "").strip().lower() == "on"


def _resolve_skills() -> tuple[str, list[str], str, list[str]]:
    """(discovery_skill, discovery_tools, verify_skill, verify_tools) for the
    current ``RF_SKILL_MODE`` — the one place the switch is applied."""
    if _test_mode():
        return (
            DISCOVERY_SKILL_TEST, _DISCOVERY_TOOLS_TEST,
            VERIFY_SKILL_TEST, _VERIFY_TOOLS_TEST,
        )
    return (DISCOVERY_SKILL, _DISCOVERY_TOOLS, VERIFY_SKILL, _VERIFY_TOOLS)

#: Discovery's final structured output — the complete deduped candidate list,
#: a safety net beside the live ``@@CANDIDATE@@`` stream.
#:
#: ``screened`` carries discovery's Step 2.7 result for each *query* parameter,
#: and is what makes rf-verify's two-step model work: a parameter marked
#: ``pass`` cleared the spec *beyond* its guard band on a site, so verify counts
#: it confirmed instead of re-extracting it. Verify opens the datasheet only for
#: ``borderline`` / ``not_stated`` parameters — and not at all when every
#: parameter is ``pass``. (``fail`` parts are rejected at the screen and never
#: emitted, so the status is carried only for logging completeness.)
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
                        "screened": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": [
                                            "pass", "borderline", "fail", "not_stated",
                                        ],
                                    },
                                    "value": {"type": ["string", "null"]},
                                    "source": {"type": ["string", "null"]},
                                },
                                "required": ["name", "status"],
                            },
                        },
                    },
                    "required": ["model"],
                },
            }
        },
        "required": ["candidates"],
    },
}

_CANDIDATE_MARKER = "@@CANDIDATE@@"
_REJECT_MARKER = "@@REJECT@@"


def _extract_marked(buffer: str, marker: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull ``<marker> {json}`` lines out of streamed discovery text.

    Buffered line parsing: only complete lines (those followed by a newline) are
    parsed; the trailing partial line is returned to be completed by the next
    chunk. Every complete line is scanned, so calling this once per marker on the
    SAME buffer never loses a line (each call ignores lines it does not own and
    returns the identical trailing remainder). Returns ``(remainder, [obj, ...])``.
    """
    *lines, remainder = buffer.split("\n")
    found: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith(marker):
            continue
        payload = line[len(marker):].strip()
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("model"):
            found.append(obj)
    return remainder, found


def _extract_candidates(buffer: str) -> tuple[str, list[dict[str, Any]]]:
    """``@@CANDIDATE@@ {json}`` lines from streamed discovery text (see
    :func:`_extract_marked`)."""
    return _extract_marked(buffer, _CANDIDATE_MARKER)


def _extract_rejects(buffer: str) -> tuple[str, list[dict[str, Any]]]:
    """``@@REJECT@@ {json}`` lines — parts discovery dropped at the site screen
    (see :func:`_extract_marked`). Symmetric to :func:`_extract_candidates`."""
    return _extract_marked(buffer, _REJECT_MARKER)


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    """Dedup key for a candidate: (model, manufacturer), case-insensitive."""
    return (
        str(candidate.get("model", "")).strip().lower(),
        str(candidate.get("manufacturer", "")).strip().lower(),
    )


def _reject_reason(reject: dict[str, Any]) -> str:
    """Human reason for a structured verify reject with no explicit ``reason``.

    Falls back to ``"<param>: found <found> vs required <required>"`` from the
    fields the schema carries, so a rejection is never reasonless in the log.
    """
    param = reject.get("param")
    if not param:
        return "rejected"
    found = reject.get("found")
    required = reject.get("required")
    return f"{param}: found {found} vs required {required}"


def _discovery_prompt(spec_text: str, skill: str = DISCOVERY_SKILL) -> str:
    return (
        f"Use the {skill} skill to find RF components matching the parameters "
        "below. Emit each surviving candidate immediately on its own line as "
        "`@@CANDIDATE@@ {json}` (model, manufacturer, url), and also return the "
        "full candidates list at the end. Do NOT read datasheets or decide final "
        "matches — that happens downstream.\n\n"
        f"Search parameters (separated by ' | '):\n{spec_text}"
    )


def _format_screened(screened: Any) -> str:
    """Render discovery's per-parameter site-screen results for the verify prompt.

    Each entry is ``{name, status, value, source}`` — see ``DISCOVERY_SCHEMA``.
    rf-verify treats ``pass`` as confirmed (the site value cleared the spec beyond
    the parameter's guard band) and settles ``borderline`` / ``not_stated`` against
    the datasheet, so passing this through is what stops verify re-extracting what
    discovery already established.

    Returns ``""`` when discovery recorded nothing usable; verify then falls back
    to settling every parameter itself — correct, just slower.
    """
    if not isinstance(screened, list):
        return ""
    lines: list[str] = []
    for entry in screened:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        bits = [f"  - {entry['name']}: {entry.get('status') or 'not_stated'}"]
        if entry.get("value"):
            bits.append(f"site value = {entry['value']}")
        if entry.get("source"):
            bits.append(f"source = {entry['source']}")
        lines.append(" | ".join(bits))
    if not lines:
        return ""
    return (
        "\n\nSite-screen results from discovery, one line per query parameter "
        "(`pass` = cleared the spec beyond its guard band on the site → count it "
        "confirmed, do NOT re-extract it; `borderline`/`not_stated` = settle it "
        "against the datasheet):\n" + "\n".join(lines)
    )


def _verify_prompt(candidate: dict[str, Any], spec_text: str, skill: str = VERIFY_SKILL) -> str:
    return (
        f"Use the {skill} skill to verify this ONE candidate against the spec. "
        "Return exactly the skill's result — do NOT invent, add, or modify it. If "
        "it does not qualify, return an empty components list.\n\n"
        f"Candidate: model={candidate.get('model', '')}, "
        f"manufacturer={candidate.get('manufacturer', '')}, "
        f"url={candidate.get('url', '')}\n"
        f"Spec (parameters, separated by ' | '):\n{spec_text}"
        f"{_format_screened(candidate.get('screened'))}"
    )


async def run_rf_search_pipelined(
    spec_text: str,
    *,
    on_text: Callable[[str], None] = print,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    on_component: Callable[[dict[str, Any]], None] | None = None,
    on_tokens: Callable[[dict[str, Any]], None] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
    max_concurrency: int = 4,
) -> Any:
    """Conductor: run ``rf-discovery`` (streaming) and fire one ``rf-verify`` run
    per candidate the instant it surfaces.

    Run logging is owned here: an ``RF_LOG``-driven :class:`RunLogger` (or a
    no-op) captures the whole run to ``runs/<timestamp>/`` and a live console
    feed — no GUI or skill involvement. ``on_event`` is an optional extra sink
    (used by tests) that receives the same events regardless of ``RF_LOG``.

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

    # Resolve which skills + tools this run uses (real web/Gemini, or the offline
    # local-JSON test skills) once — RF_SKILL_MODE decides.
    disc_skill, disc_tools, verify_skill, verify_tools = _resolve_skills()
    if _test_mode():
        on_text("[RF_SKILL_MODE=test — offline: local JSON only, no web/Gemini]\n")

    seen: set[tuple[str, str]] = set()
    tasks: list[asyncio.Task] = []
    components: list[dict[str, Any]] = []
    totals = {"tokens": 0, "num_turns": 0}
    token_totals = {k: 0 for k in _TOKEN_KINDS}
    sem = asyncio.Semaphore(max(1, max_concurrency))
    stopped = False

    # Resume (RF_RESUME): read the recent run logs for this same query BEFORE the
    # new run's own dir is created, so the fresh (empty) dir never consumes a
    # lookback slot. Off -> None, and the conductor behaves exactly as before.
    runs_base = os.path.join(PROJECT_ROOT, "runs")
    resume_state = (
        resume_mod.load_resume_state(runs_base, spec_text)
        if _resume_enabled()
        else None
    )

    # Run logging: RF_LOG decides file+console; `emit` also forwards to an
    # optional external sink so callers/tests can observe events unconditionally.
    logger = make_run_logger(_logging_enabled(), runs_base)
    rejected_count = 0   # rebindable via `nonlocal` in the verify closure

    def emit(event: dict[str, Any]) -> None:
        logger.emit(event)
        if on_event is not None:
            on_event(event)

    emit({
        "kind": run_log.RUN_STARTED, "agent_id": "run",
        "run_dir": logger.run_dir, "spec_text": spec_text,
    })

    def _accumulate(m: dict[str, Any]) -> None:
        totals["tokens"] += (m.get("tokens") or 0)
        totals["num_turns"] += (m.get("num_turns") or 0)
        for kind, value in (m.get("token_breakdown") or {}).items():
            if kind in token_totals:
                token_totals[kind] += value
        # Live tick: fires once per finished agent (discovery, then each verify),
        # so the caller can show the running total climb mid-run.
        if on_tokens is not None:
            on_tokens({
                "tokens": totals["tokens"],
                "num_turns": totals["num_turns"],
                "token_breakdown": dict(token_totals),
            })

    async def _verify(candidate: dict[str, Any]) -> None:
        nonlocal rejected_count
        agent_id = f"verify[{candidate.get('model', '?')}]"
        async with sem:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                result = await run_agent_skill(
                    _verify_prompt(candidate, spec_text, verify_skill),
                    skills=[verify_skill],
                    allowed_tools=verify_tools,
                    model="opus",
                    on_text=on_text,
                    output_format=COMPONENT_SCHEMA,
                    on_result=_accumulate,
                    on_event=emit,
                    agent_id=agent_id,
                )
            except Exception:
                # One failed verify (error/rate-limit on that call) must not kill
                # the whole pipeline; its candidate is dropped — but no longer
                # silently: the drop is recorded so it is visible in the log.
                # Marked `failed_infra` so a resume retries it rather than treating
                # it as a settled rejection.
                rejected_count += 1
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": agent_id,
                    "status": "rejected", "reason": "verify failed (error/rate-limit)",
                    "outcome": run_log.OUTCOME_FAILED_INFRA,
                })
                return
            comps = (result or {}).get("components", [])
            for comp in comps:
                components.append(comp)
                if on_component is not None:
                    on_component(comp)
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": agent_id,
                    "status": "kept", "model": comp.get("model"),
                    "verdict": comp.get("verdict", ""),
                    "outcome": run_log.OUTCOME_KEPT,
                })
            # Structured rejects (rf-verify's `rejected[]`, when present) carry a
            # reason; otherwise an empty result is itself a rejection. Classify the
            # reason so a dead-Gemini "insufficient verification" is `failed_infra`
            # (retried on resume), not a final `rejected_mismatch`.
            rejects = (result or {}).get("rejected", [])
            for r in rejects:
                rejected_count += 1
                reason = r.get("reason") or _reject_reason(r)
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": agent_id,
                    "status": "rejected", "model": r.get("model", candidate.get("model")),
                    "param": r.get("param"), "found": r.get("found"),
                    "required": r.get("required"),
                    "reason": reason,
                    "outcome": run_log.classify_verify_outcome("rejected", reason),
                })
            if not comps and not rejects:
                rejected_count += 1
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": agent_id,
                    "status": "rejected", "reason": "no qualifying match",
                    "outcome": run_log.OUTCOME_REJECTED_MISMATCH,
                })

    def _spawn(candidate: dict[str, Any]) -> None:
        key = _candidate_key(candidate)
        if key in seen:
            return
        seen.add(key)
        emit({
            "kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery",
            "model": candidate.get("model"),
            "manufacturer": candidate.get("manufacturer", ""),
            "url": candidate.get("url", ""),
            "screened": candidate.get("screened"),
        })
        tasks.append(asyncio.create_task(_verify(candidate)))

    def _seed_resume(state: resume_mod.ResumeState, *, load_all: bool) -> None:
        """Seed the pipeline from prior runs' settled work (resume).

        For each candidate a matching prior run recorded:
        - a FINAL verdict (``kept`` / genuine ``rejected_mismatch``) is replayed as
          ``reused`` events and NOT re-verified — a kept part is passed straight
          through to the results;
        - a non-final candidate (``failed_infra`` or never verified) is re-verified
          now when discovery is being skipped (``load_all``), or left for the
          re-run of discovery to resurface and verify (``load_all`` false).

        Adding a final candidate to ``seen`` is what stops a re-running discovery
        from verifying it again.
        """
        nonlocal rejected_count
        for model_key, cand in state.candidates.items():
            key = _candidate_key(cand)
            if key in seen:
                continue
            final = state.final_outcome(model_key)
            if final is None and not load_all:
                # Discovery will re-run and resurface this candidate; verify it
                # fresh then. Do NOT seed it (leave it out of `seen`).
                continue
            seen.add(key)
            model = cand.get("model")
            v_agent = f"verify[{model or '?'}]"
            emit({
                "kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery",
                "model": model, "manufacturer": cand.get("manufacturer", ""),
                "url": cand.get("url", ""), "screened": cand.get("screened"),
                "reused": True,
            })
            if final == run_log.OUTCOME_KEPT:
                comp = state.kept_result(model_key)
                if comp is not None:
                    components.append(comp)
                    if on_component is not None:
                        on_component(comp)
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": v_agent,
                    "status": "kept", "model": model,
                    "verdict": (comp or {}).get("verdict", ""),
                    "outcome": run_log.OUTCOME_KEPT, "reused": True,
                })
            elif final == run_log.OUTCOME_REJECTED_MISMATCH:
                rejected_count += 1
                emit({
                    "kind": run_log.VERIFY_RESULT, "agent_id": v_agent,
                    "status": "rejected", "model": model,
                    "reason": state.mismatch_reason(model_key),
                    "outcome": run_log.OUTCOME_REJECTED_MISMATCH, "reused": True,
                })
            else:
                # load_all and not final -> re-verify this candidate now.
                tasks.append(asyncio.create_task(_verify(cand)))

    # Resume seeding: replay settled work, decide whether discovery can be skipped.
    skip_discovery = bool(resume_state and resume_state.discovery_clean)
    if resume_state is not None:
        _seed_resume(resume_state, load_all=skip_discovery)

    disc_meta: dict[str, Any] = {}
    disc_candidates: list[dict[str, Any]] = []

    if skip_discovery:
        # A matching prior run finished discovery cleanly; its candidates were
        # loaded and seeded above. Record a carried-over clean discovery so THIS
        # run stays independently resumable, and synthesize a success meta.
        emit({
            "kind": run_log.AGENT_FINISHED, "agent_id": "discovery",
            "subtype": "success", "is_error": False,
            "num_turns": 0, "tokens": 0, "reused": True,
        })
        disc_meta = {"subtype": "success", "is_error": False,
                     "num_turns": 0, "tokens": 0}
    else:
        options = ClaudeAgentOptions(
            cwd=PROJECT_ROOT,
            setting_sources=["user", "project"],
            skills=[disc_skill],
            allowed_tools=disc_tools,
            model="opus",
            permission_mode="acceptEdits",
            output_format=DISCOVERY_SCHEMA,
        )

        buffer = ""

        async with ClaudeSDKClient(options=options) as client:
            await client.query(_discovery_prompt(spec_text, disc_skill))
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
                            combined = buffer + text
                            buffer, fresh = _extract_candidates(combined)
                            for cand in fresh:
                                _spawn(cand)   # verify starts NOW, mid-discovery
                            # Same combined buffer, other marker — the two scans
                            # return the identical remainder, so nothing is lost.
                            _, rejects = _extract_rejects(combined)
                            for rej in rejects:
                                rejected_count += 1
                                emit({
                                    "kind": run_log.REJECT, "agent_id": "discovery",
                                    "model": rej.get("model"),
                                    "manufacturer": rej.get("manufacturer", ""),
                                    "param": rej.get("param"),
                                    "site_value": rej.get("site_value"),
                                    "reason": rej.get("reason", ""),
                                })
                            continue
                        # Non-text blocks are discovery's ground-truth actions.
                        ev = block_to_event(block, "discovery")
                        if ev is not None:
                            emit(ev)
                elif isinstance(message, ResultMessage):
                    on_text(f"\n[discovery done: {message.subtype}]")
                    disc_meta = {
                        "subtype": message.subtype,
                        "is_error": bool(getattr(message, "is_error", False)),
                        "api_error_status": getattr(message, "api_error_status", None),
                        "stop_reason": getattr(message, "stop_reason", None),
                        "num_turns": getattr(message, "num_turns", None),
                        "tokens": _sum_tokens(getattr(message, "usage", None)),
                        "token_breakdown": _token_breakdown(getattr(message, "usage", None)),
                    }
                    _accumulate(disc_meta)
                    so = getattr(message, "structured_output", None)
                    if isinstance(so, dict):
                        disc_candidates = so.get("candidates") or []
                    emit({
                        "kind": run_log.COVERAGE, "agent_id": "discovery",
                        "text": getattr(message, "result", None) or "",
                    })
                    emit({
                        "kind": run_log.AGENT_FINISHED, "agent_id": "discovery",
                        "subtype": disc_meta.get("subtype"),
                        "is_error": disc_meta.get("is_error"),
                        "num_turns": disc_meta.get("num_turns"),
                        "tokens": disc_meta.get("tokens"),
                    })

        # Safety net: verify any final-list candidate discovery didn't stream
        # (unless the user stopped — then don't start new work).
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
        "token_breakdown": dict(token_totals),
        "stopped": stopped,
    }
    if on_result is not None:
        on_result(meta)

    # Close out the log: a final banner + the derived summary.md.
    summary_path = os.path.join(logger.run_dir, "summary.md") if logger.run_dir else ""
    emit({
        "kind": run_log.RUN_FINISHED, "agent_id": "run",
        "found": len(seen), "rejected": rejected_count,
        "kept": len(components), "summary": summary_path,
    })
    logger.finish()

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
    on_tokens: Callable[[dict[str, Any]], None] | None = None,
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
        on_tokens=on_tokens,
        stop_event=stop_event,
    )
