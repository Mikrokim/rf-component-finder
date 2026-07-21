"""AI Search run logging — the one place all logging machinery lives.

An AI Search run (``rf-discovery`` → ``rf-verify``) emits a single stream of
typed **events**; this module fans that stream to two sinks at once: a live
console feed (so the run is visible in real time from the terminal it was
launched in) and an append-only ``events.jsonl`` file, plus a human-readable
``summary.md`` written when the run ends.

Design (see openspec/changes/add-ai-search-run-logging/design.md):
- The conductor describes *what* happened (``kind`` + fields); the ``RunLogger``
  stamps *when/order* (``seq`` + ``ts``), persists, and renders. Callers never
  format or touch files.
- ``RF_LOG`` is resolved in ``skill_runner`` (``_logging_enabled``); when off the
  conductor uses :class:`NullRunLogger`, so every call site is unconditional.
- The skills know nothing about this — they only emit their usual markers.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Any


def _safe_print(line: str) -> None:
    """Print one console line, never raising — even if stdout's encoding cannot
    represent a character (a stray non-ASCII field on a cp1252 console prints
    with replacements rather than vanishing)."""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
        except Exception:
            pass
    except Exception:
        pass


# --- Event kinds -----------------------------------------------------------

#: A tool the agent invoked (WebFetch/WebSearch/Bash/Read…); the ground truth
#: for "which site did it visit", taken from the real tool call.
TOOL_CALL = "tool_call"
#: A datasheet read via Gemini — a Bash call to ``run_extract.py``, recognized
#: and surfaced explicitly (url + params) instead of as an opaque shell line.
DATASHEET_READ = "datasheet_read"
#: The result of a tool call (carries ``is_error``).
TOOL_RESULT = "tool_result"
#: A candidate discovery surfaced (carries its ``screened`` array).
CANDIDATE_FOUND = "candidate_found"
#: A part rejected at discovery's Step 2.7 site screen (``@@REJECT@@``).
REJECT = "reject"
#: The outcome of one verify run: kept or rejected.
VERIFY_RESULT = "verify_result"
#: An agent (discovery or a verify) finished — subtype, error, turns, tokens.
AGENT_FINISHED = "agent_finished"
#: Discovery's verbatim final coverage statement (human context only).
COVERAGE = "coverage"
#: Run boundaries.
RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"


# --- SDK block → event (duck-typed, no SDK import) -------------------------

#: Per tool, the ``input`` key that names *what* it acted on. Falls back to a
#: best-effort scan when a tool is not listed.
_TARGET_KEYS: dict[str, str] = {
    "webfetch": "url",
    "web_fetch": "url",
    "websearch": "query",
    "web_search": "query",
    "bash": "command",
    "read": "file_path",
    "grep": "pattern",
    "glob": "pattern",
}


def _tool_target(name: str, inp: dict[str, Any]) -> str:
    """Best-effort "what did this tool act on" string from a tool's ``input``."""
    if not isinstance(inp, dict):
        return ""
    key = _TARGET_KEYS.get(name.lower())
    if key and inp.get(key):
        return str(inp[key])
    # Unknown tool: first non-empty string value, else the compact JSON.
    for value in inp.values():
        if isinstance(value, str) and value:
            return value
    try:
        return json.dumps(inp, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


_DS_URL = re.compile(r"--url\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
_DS_PARAMS = re.compile(r"--params\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))")


def _match_one(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    if not m:
        return ""
    return next((g for g in m.groups() if g), "")


def block_to_event(block: Any, agent_id: str) -> dict[str, Any] | None:
    """Turn one SDK content block into an event dict, or ``None`` to skip it.

    Duck-typed (matching ``skill_runner``'s existing ``getattr(block, "text")``
    style) so it needs no SDK class import and works against the test fakes:

    - a **text**/thinking block → ``None`` (text is handled by the caller; the
      model's reasoning is deliberately not logged);
    - a **tool-use** / server-tool-use block (has ``name`` + ``input``) →
      ``tool_call``, or ``datasheet_read`` when it is the Gemini runner;
    - a **tool-result** block (has ``tool_use_id``) → ``tool_result``.
    """
    if getattr(block, "text", None) is not None:
        return None  # plain text — the caller streams/parses it

    name = getattr(block, "name", None)
    if name is not None and hasattr(block, "input"):
        inp = getattr(block, "input") or {}
        command = str(inp.get("command", "")) if isinstance(inp, dict) else ""
        if name.lower() == "bash" and "run_extract.py" in command:
            return {
                "kind": DATASHEET_READ,
                "agent_id": agent_id,
                "url": _match_one(_DS_URL, command),
                "params": _match_one(_DS_PARAMS, command),
            }
        return {
            "kind": TOOL_CALL,
            "agent_id": agent_id,
            "tool": str(name),
            "target": _tool_target(str(name), inp),
        }

    tool_use_id = getattr(block, "tool_use_id", None)
    if tool_use_id is not None:
        return {
            "kind": TOOL_RESULT,
            "agent_id": agent_id,
            "tool_use_id": str(tool_use_id),
            "is_error": bool(getattr(block, "is_error", False)),
        }

    return None  # thinking or anything else we do not surface


# --- Console rendering -----------------------------------------------------

def format_console_line(event: dict[str, Any]) -> str | None:
    """Render one event as a single console line, or ``None`` to print nothing.

    The live feed shows actions, candidates, and rejections (not the model's
    internal reasoning, and not the verbose coverage text — those still go to
    the file). ASCII-only glyphs: the Windows console is often cp1252, where a
    stray ``→``/``▶`` raises ``UnicodeEncodeError`` and the line would be lost."""
    kind = event.get("kind")
    agent = event.get("agent_id", "?")
    tag = f"[{agent}]"

    if kind == RUN_STARTED:
        return f"=== AI Search run -> {event.get('run_dir', '')} ==="
    if kind == RUN_FINISHED:
        return (
            f"=== run complete: {event.get('found', 0)} found, "
            f"{event.get('rejected', 0)} rejected -> {event.get('summary', '')} ==="
        )
    if kind == TOOL_CALL:
        return f"{tag} {event.get('tool', '?')} -> {event.get('target', '')}"
    if kind == DATASHEET_READ:
        params = event.get("params", "")
        suffix = f"  params: {params}" if params else ""
        return f"{tag} Gemini >> reading datasheet  {event.get('url', '')}{suffix}"
    if kind == TOOL_RESULT:
        if event.get("is_error"):
            return f"{tag} [x] tool result error"
        return None  # successful results are file-only noise on the console
    if kind == CANDIDATE_FOUND:
        return (
            f"{tag} candidate -> {event.get('model', '?')} "
            f"({event.get('manufacturer', '')}){_screened_brief(event.get('screened'))}"
        )
    if kind == REJECT:
        return (
            f"{tag} reject -> {event.get('model', '?')}  "
            f"{event.get('param', '')} {event.get('site_value', '')} "
            f"({event.get('reason', '')})"
        )
    if kind == VERIFY_RESULT:
        if event.get("status") == "kept":
            return f"{tag} result -> kept \"{event.get('verdict', '')}\""
        reason = event.get("reason") or ""
        return f"{tag} result -> REJECTED {reason}".rstrip()
    if kind == AGENT_FINISHED:
        # tokens/turns may be None (a run with no usage reported) — coerce so the
        # thousands-format never hits None.
        return (
            f"{tag} finished ({event.get('subtype', '?')}, "
            f"{event.get('num_turns') or 0} turns, {event.get('tokens') or 0:,} tok)"
        )
    return None  # coverage and any future kinds: file-only


def _screened_brief(screened: Any) -> str:
    """Compact `` name=status`` list for the console, or ``""``."""
    if not isinstance(screened, list) or not screened:
        return ""
    bits = [
        f"{e.get('name')}={e.get('status')}"
        for e in screened
        if isinstance(e, dict) and e.get("name")
    ]
    return "  " + " ".join(bits) if bits else ""


# --- Summary ---------------------------------------------------------------

_WEBISH = {"webfetch", "web_fetch", "websearch", "web_search"}


def render_summary(events: list[dict[str, Any]]) -> str:
    """Build ``summary.md`` text from the captured events.

    Counts are DERIVED from the structured events (not the model's prose): the
    coverage statement is included verbatim for context but is never the source
    of the numbers."""
    sites: list[str] = []
    found: list[dict[str, Any]] = []
    rejections: list[str] = []
    coverage = ""
    tokens = 0
    turns = 0

    for e in events:
        kind = e.get("kind")
        if kind == TOOL_CALL and str(e.get("tool", "")).lower() in _WEBISH:
            _add_unique(sites, e.get("target", ""))
        elif kind == DATASHEET_READ:
            _add_unique(sites, e.get("url", ""))
        elif kind == CANDIDATE_FOUND:
            found.append(e)
        elif kind == REJECT:
            rejections.append(
                f"- **{e.get('model', '?')}** - {e.get('param', '')} "
                f"{e.get('site_value', '')} ({e.get('reason', '')}) | site-screen"
            )
        elif kind == VERIFY_RESULT and e.get("status") == "rejected":
            rejections.append(
                f"- **{e.get('model', '?')}** - {e.get('reason', 'rejected')} "
                f"| {e.get('agent_id', '')}"
            )
        elif kind == COVERAGE:
            coverage = str(e.get("text", "") or "")
        elif kind == AGENT_FINISHED:
            tokens += int(e.get("tokens", 0) or 0)
            turns += int(e.get("num_turns", 0) or 0)

    lines = [
        "# AI Search run summary",
        "",
        f"- **Candidates found:** {len(found)}",
        f"- **Rejected:** {len(rejections)}",
        f"- **Sites/sources visited:** {len(sites)}",
        f"- **Cost:** {tokens:,} tokens | {turns} turns",
        "",
        "## Sites / sources visited",
        "",
        *([f"- {s}" for s in sites] or ["- (none)"]),
        "",
        "## Rejections (with reasons)",
        "",
        *(rejections or ["- (none)"]),
        "",
        "## Candidates found",
        "",
        *(
            [f"- {c.get('model', '?')} ({c.get('manufacturer', '')})" for c in found]
            or ["- (none)"]
        ),
        "",
        "## Coverage statement (verbatim)",
        "",
        coverage or "_(none captured)_",
        "",
    ]
    return "\n".join(lines)


def _add_unique(acc: list[str], value: Any) -> None:
    v = str(value or "").strip()
    if v and v not in acc:
        acc.append(v)


# --- The logger ------------------------------------------------------------

class RunLogger:
    """Live-writes ``events.jsonl`` and the console feed; ``finish`` → summary.

    Constructed with an explicit ``run_dir`` (already created). Use
    :func:`make_run_logger` in normal code, which resolves the timestamped dir
    under ``base_dir``; tests pass their own directory.
    """

    def __init__(self, run_dir: str) -> None:
        self.run_dir = run_dir
        self.events: list[dict[str, Any]] = []
        self._seq = 0
        self._events_path = os.path.join(run_dir, "events.jsonl")
        # Line-buffered append; each emit also flushes so a partial run is
        # readable and survives a crash mid-way.
        self._fh = open(self._events_path, "a", encoding="utf-8")

    def emit(self, event: dict[str, Any]) -> None:
        """Stamp, persist, and print one event. Never raises into the caller."""
        self._seq += 1
        stamped = {
            "seq": self._seq,
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            **event,
        }
        self.events.append(stamped)
        # File and console are independent: a console encoding failure must not
        # cost the durable file line, and vice versa. Logging never raises into
        # the caller.
        try:
            self._fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception:
            pass
        try:
            line = format_console_line(stamped)
        except Exception:
            line = None   # a formatting bug must never break the run
        if line is not None:
            _safe_print(line)

    def finish(self) -> str | None:
        """Write ``summary.md`` from the captured events; return its path."""
        summary_path = os.path.join(self.run_dir, "summary.md")
        try:
            with open(summary_path, "w", encoding="utf-8") as fh:
                fh.write(render_summary(self.events))
        except Exception:
            pass
        finally:
            self.close()
        return summary_path

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class NullRunLogger:
    """No-op logger used when ``RF_LOG`` is off, so call sites are unconditional."""

    run_dir = None

    def emit(self, event: dict[str, Any]) -> None:  # noqa: D401 - trivial
        pass

    def finish(self) -> str | None:
        return None

    def close(self) -> None:
        pass


def make_run_logger(enabled: bool, base_dir: str) -> RunLogger | NullRunLogger:
    """Return a real :class:`RunLogger` (timestamped dir under ``base_dir``) when
    ``enabled``, else a :class:`NullRunLogger`. The single seam the conductor
    uses; the ``RF_LOG`` decision is made by the caller."""
    if not enabled:
        return NullRunLogger()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = os.path.join(base_dir, stamp)
    os.makedirs(run_dir, exist_ok=True)
    return RunLogger(run_dir)
