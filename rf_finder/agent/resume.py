"""Resume state: reconstruct what prior AI Search runs already settled.

When ``RF_RESUME`` is on, a re-run of the same query continues from earlier runs
instead of redoing settled work. This module is the *reading* half — it scans the
recent ``runs/<timestamp>/events.jsonl`` logs, keeps the ones whose stored query
(``spec_text``) matches, and reconstructs a :class:`ResumeState`. The conductor
(:mod:`rf_finder.agent.skill_runner`) does the *acting* on that state: skipping a
cleanly-finished discovery and reusing final verify verdicts.

Design (see openspec/changes/add-ai-search-resume/design.md):
- Query identity is the form's ``spec_text``, stored on the ``RUN_STARTED`` event.
- Only the 4 most-recent run directories (by timestamped name) are considered.
- Discovery is "clean" (skippable) when any matching run has a discovery
  ``AGENT_FINISHED`` with ``is_error`` false — discovery uses no Gemini, so a
  clean finish means its candidate list is complete.
- A verify verdict is reusable only when final (``kept`` / ``rejected_mismatch``);
  ``failed_infra`` (dead Gemini / "insufficient verification" / rate-limit) is
  retried. Classification is centralized in
  :func:`rf_finder.agent.run_log.classify_verify_outcome`.
- Parsing is tolerant: unreadable dirs/lines are skipped, and a prior log without
  a ``spec_text`` (written before this feature) simply never matches — so an
  older run degrades to "nothing to reuse", never an error.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from rf_finder.agent import run_log

#: How many of the most-recent run directories resume looks back through.
LOOKBACK_RUNS = 4

_VERIFY_AGENT = re.compile(r"verify\[(.*)\]\s*$")


def _model_key(model: Any) -> str:
    """Reuse key for a candidate/verify: its model, case-folded and stripped.

    Verify events reliably carry only the model (in ``agent_id`` = ``verify[M]``),
    so resume keys on the model alone — unique enough within a run."""
    return str(model or "").strip().lower()


def _verify_model(event: dict[str, Any]) -> str:
    """The model a ``VERIFY_RESULT`` is about — its explicit ``model`` field, or
    the ``M`` parsed out of an ``agent_id`` of the form ``verify[M]``."""
    model = event.get("model")
    if model:
        return str(model)
    match = _VERIFY_AGENT.match(str(event.get("agent_id", "")))
    return match.group(1) if match else ""


@dataclass
class ResumeState:
    """Merged, reusable state reconstructed from the matching prior runs.

    - ``discovery_clean``: at least one matching run finished discovery cleanly,
      so the current run may skip discovery and load candidates from the log.
    - ``candidates``: ``model_key -> {model, manufacturer, url, screened}`` for
      every candidate seen across the matching runs (newest run's data wins).
    - ``outcomes``: ``model_key -> {outcome, verdict, reason}`` for every candidate
      that was verified (newest run's verdict wins).
    """

    discovery_clean: bool = False
    candidates: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def has_matches(self) -> bool:
        """True when any matching prior run contributed candidates or verdicts."""
        return bool(self.candidates or self.outcomes)

    def final_outcome(self, model_key: str) -> str | None:
        """The final outcome for a candidate (``kept`` / ``rejected_mismatch``), or
        ``None`` when it was never verified or its last verify was
        ``failed_infra`` — i.e. it still needs verifying."""
        entry = self.outcomes.get(model_key)
        if not entry:
            return None
        code = entry.get("outcome")
        if code in (run_log.OUTCOME_KEPT, run_log.OUTCOME_REJECTED_MISMATCH):
            return code
        return None

    def kept_result(self, model_key: str) -> dict[str, Any] | None:
        """The kept component to pass straight through, rebuilt from the candidate
        (model/manufacturer/url) and the verify verdict — or ``None`` if this
        candidate was not a kept match."""
        entry = self.outcomes.get(model_key)
        cand = self.candidates.get(model_key)
        if not entry or entry.get("outcome") != run_log.OUTCOME_KEPT or not cand:
            return None
        return {
            "model": cand.get("model"),
            "manufacturer": cand.get("manufacturer", ""),
            "url": cand.get("url", ""),
            "verdict": entry.get("verdict", ""),
        }

    def mismatch_reason(self, model_key: str) -> str:
        """The recorded reason a candidate was rejected as a genuine mismatch."""
        entry = self.outcomes.get(model_key) or {}
        return str(entry.get("reason") or "rejected")


def _recent_run_dirs(runs_base: str, lookback: int) -> list[str]:
    """The ``lookback`` most-recent run directories under ``runs_base``, newest
    first. The logger names dirs ``%Y%m%d_%H%M%S_%f``, which sorts
    lexicographically in chronological order — so a reverse name sort is newest
    first. A missing/unreadable ``runs_base`` yields ``[]``."""
    try:
        entries = os.listdir(runs_base)
    except OSError:
        return []
    dirs = [
        os.path.join(runs_base, name)
        for name in entries
        if os.path.isdir(os.path.join(runs_base, name))
    ]
    dirs.sort(key=os.path.basename, reverse=True)
    return dirs[:lookback]


def _parse_run(run_dir: str) -> dict[str, Any] | None:
    """Reduce one run's ``events.jsonl`` to the fields resume needs, tolerantly.

    Returns ``{spec_text, discovery_clean, candidates, outcomes}`` or ``None`` when
    there is no readable events file. Unparseable lines are skipped; a missing
    ``spec_text`` stays ``None`` (so the run never matches a real query)."""
    path = os.path.join(run_dir, "events.jsonl")
    if not os.path.isfile(path):
        return None

    spec_text: str | None = None
    discovery_clean = False
    candidates: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}

    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("kind")

                if kind == run_log.RUN_STARTED:
                    if event.get("spec_text") is not None:
                        spec_text = str(event.get("spec_text"))
                elif (
                    kind == run_log.AGENT_FINISHED
                    and event.get("agent_id") == "discovery"
                    and not event.get("is_error")
                ):
                    discovery_clean = True
                elif kind == run_log.CANDIDATE_FOUND:
                    key = _model_key(event.get("model"))
                    if key:
                        candidates[key] = {
                            "model": event.get("model"),
                            "manufacturer": event.get("manufacturer", ""),
                            "url": event.get("url", ""),
                            "screened": event.get("screened"),
                        }
                elif kind == run_log.VERIFY_RESULT:
                    key = _model_key(_verify_model(event))
                    if not key:
                        continue
                    code = event.get("outcome") or run_log.classify_verify_outcome(
                        str(event.get("status", "")), event.get("reason")
                    )
                    # Last verdict within a run wins (a single candidate normally
                    # emits one); across runs the newest run wins (see load).
                    outcomes[key] = {
                        "outcome": code,
                        "verdict": event.get("verdict", ""),
                        "reason": event.get("reason", ""),
                    }
    except OSError:
        return None

    return {
        "spec_text": spec_text,
        "discovery_clean": discovery_clean,
        "candidates": candidates,
        "outcomes": outcomes,
    }


def load_resume_state(
    runs_base: str, spec_text: str, *, lookback: int = LOOKBACK_RUNS
) -> ResumeState:
    """Build the merged :class:`ResumeState` for ``spec_text`` from the recent runs.

    Scans the ``lookback`` most-recent run dirs, keeps those whose stored
    ``spec_text`` equals the current query, then merges newest-first: discovery is
    clean if ANY matching run finished it cleanly, and per candidate the newest
    run's data/verdict wins (``setdefault`` over a newest-first list). Returns an
    empty state (``has_matches`` False) when nothing matches — the conductor then
    runs fresh."""
    matching: list[dict[str, Any]] = []
    for run_dir in _recent_run_dirs(runs_base, lookback):  # newest first
        parsed = _parse_run(run_dir)
        if parsed and parsed["spec_text"] is not None and parsed["spec_text"] == spec_text:
            matching.append(parsed)

    discovery_clean = any(p["discovery_clean"] for p in matching)
    candidates: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    for parsed in matching:  # newest first: setdefault keeps the newest
        for key, cand in parsed["candidates"].items():
            candidates.setdefault(key, cand)
        for key, entry in parsed["outcomes"].items():
            outcomes.setdefault(key, entry)

    return ResumeState(
        discovery_clean=discovery_clean,
        candidates=candidates,
        outcomes=outcomes,
    )
