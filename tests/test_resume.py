"""Tests for resume-state reconstruction (``rf_finder.agent.resume``).

No SDK and no network: fabricated ``runs/<name>/events.jsonl`` files stand in for
real runs. Covers the lookback window, ``spec_text`` filtering, tolerant parsing,
the merge rules (newest-verdict-wins, any-clean-discovery), the kept-result
rebuild, and the outcome classification (notably "insufficient verification" =>
``failed_infra`` => retried, not final).
"""

from __future__ import annotations

import json
import os

from rf_finder.agent import resume, run_log


# --- helpers ---------------------------------------------------------------


def _write_run(base, name, events):
    """Create ``base/<name>/events.jsonl`` from a list of event dicts."""
    run_dir = base / name
    run_dir.mkdir()
    with open(run_dir / "events.jsonl", "w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return run_dir


def _started(spec):
    return {"kind": run_log.RUN_STARTED, "agent_id": "run", "spec_text": spec}


def _discovery_finished(is_error=False):
    return {
        "kind": run_log.AGENT_FINISHED, "agent_id": "discovery",
        "subtype": "error" if is_error else "success", "is_error": is_error,
    }


def _candidate(model, manufacturer="X", url="u"):
    return {
        "kind": run_log.CANDIDATE_FOUND, "agent_id": "discovery",
        "model": model, "manufacturer": manufacturer, "url": url,
    }


def _verify(model, status, *, outcome=None, verdict="", reason=""):
    ev = {
        "kind": run_log.VERIFY_RESULT, "agent_id": f"verify[{model}]",
        "status": status, "model": model, "verdict": verdict, "reason": reason,
    }
    if outcome is not None:
        ev["outcome"] = outcome
    return ev


# --- lookback window -------------------------------------------------------


def test_recent_run_dirs_takes_four_newest_by_name(tmp_path):
    for i in range(6):
        (tmp_path / f"2026010{i}_000000_000000").mkdir()
    names = [os.path.basename(d) for d in resume._recent_run_dirs(str(tmp_path), 4)]
    assert names == [
        "20260105_000000_000000",
        "20260104_000000_000000",
        "20260103_000000_000000",
        "20260102_000000_000000",
    ]  # newest first, only four


def test_missing_runs_dir_yields_empty_state(tmp_path):
    state = resume.load_resume_state(str(tmp_path / "nope"), "SPEC")
    assert state.has_matches is False
    assert state.discovery_clean is False


def test_match_outside_window_is_ignored(tmp_path):
    # The matching run is the OLDEST of five; only the four newest are scanned.
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _discovery_finished(), _candidate("M1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT)])
    for i in range(2, 6):
        _write_run(tmp_path, f"2026010{i}_000000_000000", [_started("OTHER")])
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.has_matches is False   # aged out of the 4-run window


# --- spec_text filtering ---------------------------------------------------


def test_only_matching_spec_text_is_used(tmp_path):
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC-A"), _discovery_finished(), _candidate("M1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT, verdict="match")])
    _write_run(tmp_path, "20260102_000000_000000",
               [_started("SPEC-B"), _discovery_finished(), _candidate("Z9"),
                _verify("Z9", "kept", outcome=run_log.OUTCOME_KEPT)])

    match = resume.load_resume_state(str(tmp_path), "SPEC-A")
    assert match.discovery_clean is True
    assert "m1" in match.candidates and "z9" not in match.candidates

    miss = resume.load_resume_state(str(tmp_path), "SPEC-C")
    assert miss.has_matches is False


def test_old_log_without_spec_text_never_matches(tmp_path):
    # Pre-feature log: no RUN_STARTED spec_text -> spec_text stays None.
    _write_run(tmp_path, "20260101_000000_000000",
               [_discovery_finished(), _candidate("M1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT)])
    assert resume.load_resume_state(str(tmp_path), "SPEC").has_matches is False


# --- clean-discovery + kept reconstruction ---------------------------------


def test_clean_discovery_and_kept_result_rebuilt(tmp_path):
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _candidate("M1", manufacturer="BeRex", url="u1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT, verdict="4/4"),
                _discovery_finished(is_error=False)])
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.discovery_clean is True
    assert state.final_outcome("m1") == run_log.OUTCOME_KEPT
    assert state.kept_result("m1") == {
        "model": "M1", "manufacturer": "BeRex", "url": "u1", "verdict": "4/4",
    }


def test_incomplete_discovery_is_not_clean(tmp_path):
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _candidate("M1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT),
                _discovery_finished(is_error=True)])   # discovery errored mid-way
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.discovery_clean is False
    assert state.final_outcome("m1") == run_log.OUTCOME_KEPT   # verify still reusable


# --- outcome classification ------------------------------------------------


def test_insufficient_verification_is_failed_infra_not_final(tmp_path):
    # The dead-Gemini case, logged WITHOUT an explicit outcome (old-style) — it
    # must be classified failed_infra so resume retries rather than accepting it.
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _discovery_finished(), _candidate("M1"),
                _verify("M1", "rejected",
                        reason="insufficient verification: only 2/4 params, Gemini not available")])
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.outcomes["m1"]["outcome"] == run_log.OUTCOME_FAILED_INFRA
    assert state.final_outcome("m1") is None       # -> will be re-verified
    assert state.kept_result("m1") is None


def test_genuine_mismatch_is_final(tmp_path):
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _discovery_finished(), _candidate("M1"),
                _verify("M1", "rejected", outcome=run_log.OUTCOME_REJECTED_MISMATCH,
                        reason="band does not contain 2-6 GHz")])
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.final_outcome("m1") == run_log.OUTCOME_REJECTED_MISMATCH
    assert state.mismatch_reason("m1") == "band does not contain 2-6 GHz"


# --- merge across matching runs --------------------------------------------


def test_newest_verdict_wins_and_any_clean_discovery_counts(tmp_path):
    # Older run: M1 kept, discovery incomplete. Newer run: M1 now a mismatch,
    # discovery clean. Merge => newest verdict (mismatch) wins; discovery clean.
    _write_run(tmp_path, "20260101_000000_000000",
               [_started("SPEC"), _discovery_finished(is_error=True), _candidate("M1"),
                _verify("M1", "kept", outcome=run_log.OUTCOME_KEPT)])
    _write_run(tmp_path, "20260102_000000_000000",
               [_started("SPEC"), _discovery_finished(is_error=False), _candidate("M1"),
                _verify("M1", "rejected", outcome=run_log.OUTCOME_REJECTED_MISMATCH,
                        reason="gain too low")])
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.discovery_clean is True                       # newer run was clean
    assert state.final_outcome("m1") == run_log.OUTCOME_REJECTED_MISMATCH  # newest wins


def test_tolerant_parsing_skips_garbage_lines(tmp_path):
    run_dir = tmp_path / "20260101_000000_000000"
    run_dir.mkdir()
    with open(run_dir / "events.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps(_started("SPEC")) + "\n")
        fh.write("this is not json\n")                 # skipped
        fh.write("\n")                                  # blank, skipped
        fh.write(json.dumps(_discovery_finished()) + "\n")
        fh.write(json.dumps(_candidate("M1")) + "\n")
        fh.write(json.dumps(_verify("M1", "kept", outcome=run_log.OUTCOME_KEPT)) + "\n")
    state = resume.load_resume_state(str(tmp_path), "SPEC")
    assert state.discovery_clean is True
    assert state.final_outcome("m1") == run_log.OUTCOME_KEPT
