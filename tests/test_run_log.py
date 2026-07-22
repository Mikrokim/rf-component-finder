"""Tests for the AI Search run logger (``rf_finder.agent.run_log``).

No SDK and no network: SDK content blocks are duck-typed, so plain namespaces
stand in for them. Covers the block→event mapping (including the Gemini
datasheet recognizer), the ``events.jsonl`` write/flush/seq contract, and the
derived-from-events summary.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from rf_finder.agent import run_log
from rf_finder.agent.run_log import (
    AGENT_FINISHED,
    CANDIDATE_FOUND,
    COVERAGE,
    DATASHEET_READ,
    OUTCOME_FAILED_INFRA,
    OUTCOME_KEPT,
    OUTCOME_REJECTED_MISMATCH,
    REJECT,
    RUN_STARTED,
    TOOL_CALL,
    TOOL_RESULT,
    VERIFY_RESULT,
    NullRunLogger,
    RunLogger,
    block_to_event,
    classify_verify_outcome,
    make_run_logger,
    render_summary,
)


# --- block_to_event --------------------------------------------------------


def test_text_block_is_skipped():
    assert block_to_event(SimpleNamespace(text="hello"), "discovery") is None


def test_thinking_block_is_skipped():
    # No text, no name/input, no tool_use_id -> not surfaced.
    assert block_to_event(SimpleNamespace(thinking="hmm", signature="s"), "d") is None


def test_web_fetch_becomes_tool_call_with_url():
    block = SimpleNamespace(id="t1", name="WebFetch", input={"url": "https://everything.rf/x"})
    ev = block_to_event(block, "discovery")
    assert ev == {
        "kind": TOOL_CALL,
        "agent_id": "discovery",
        "tool": "WebFetch",
        "target": "https://everything.rf/x",
    }


def test_web_search_target_is_the_query():
    block = SimpleNamespace(id="t1", name="web_search", input={"query": "GaN amplifier 2-6 GHz"})
    ev = block_to_event(block, "discovery")
    assert ev["kind"] == TOOL_CALL and ev["target"] == "GaN amplifier 2-6 GHz"


def test_datasheet_runner_becomes_gemini_read_with_url_and_params():
    cmd = 'python "tools/run_extract.py" --url "https://d/BLB28.pdf" --params "Gain,P1dB,NF"'
    block = SimpleNamespace(id="t2", name="Bash", input={"command": cmd})
    ev = block_to_event(block, "verify[BLB28]")
    assert ev == {
        "kind": DATASHEET_READ,
        "agent_id": "verify[BLB28]",
        "url": "https://d/BLB28.pdf",
        "params": "Gain,P1dB,NF",
    }


def test_plain_bash_is_a_tool_call_not_a_datasheet_read():
    block = SimpleNamespace(id="t3", name="Bash", input={"command": "ls -la"})
    ev = block_to_event(block, "verify[X]")
    assert ev["kind"] == TOOL_CALL and ev["target"] == "ls -la"


def test_tool_result_carries_error_flag():
    block = SimpleNamespace(tool_use_id="t2", content="boom", is_error=True)
    ev = block_to_event(block, "verify[BLB28]")
    assert ev == {
        "kind": TOOL_RESULT,
        "agent_id": "verify[BLB28]",
        "tool_use_id": "t2",
        "is_error": True,
    }


# --- RunLogger emit contract -----------------------------------------------


def test_emit_assigns_increasing_seq_and_writes_one_json_line_each(tmp_path):
    logger = RunLogger(str(tmp_path))
    logger.emit({"kind": TOOL_CALL, "agent_id": "discovery", "tool": "WebFetch", "target": "u1"})
    logger.emit({"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1"})

    # Readable mid-run (flushed), before finish().
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    objs = [json.loads(ln) for ln in lines]
    assert [o["seq"] for o in objs] == [1, 2]        # increasing
    assert all("ts" in o for o in objs)               # timestamped
    assert objs[0]["tool"] == "WebFetch" and objs[1]["model"] == "M1"
    logger.close()


def test_null_logger_writes_nothing(tmp_path):
    logger = make_run_logger(enabled=False, base_dir=str(tmp_path))
    assert isinstance(logger, NullRunLogger)
    logger.emit({"kind": TOOL_CALL, "agent_id": "d", "tool": "WebFetch", "target": "u"})
    logger.finish()
    assert list(tmp_path.iterdir()) == []             # no runs dir, no files


def test_make_run_logger_creates_timestamped_dir(tmp_path):
    logger = make_run_logger(enabled=True, base_dir=str(tmp_path))
    assert isinstance(logger, RunLogger)
    assert (tmp_path).exists()
    subdirs = list(tmp_path.iterdir())
    assert len(subdirs) == 1 and subdirs[0].is_dir()  # runs/<timestamp>/
    logger.close()


# --- Summary is derived from events ----------------------------------------


def test_summary_counts_and_reasons_come_from_events(tmp_path):
    events = [
        {"kind": TOOL_CALL, "agent_id": "discovery", "tool": "WebFetch", "target": "https://everything.rf/a"},
        {"kind": DATASHEET_READ, "agent_id": "verify[M1]", "url": "https://d/M1.pdf", "params": "NF"},
        {"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "BeRex"},
        {"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M2", "manufacturer": "X"},
        {"kind": REJECT, "agent_id": "discovery", "model": "M3", "param": "NF",
         "site_value": "4.2 dB", "reason": "NF 4.2 > 1.5"},
        {"kind": VERIFY_RESULT, "agent_id": "verify[M2]", "status": "rejected",
         "reason": "freq band does not contain 2-6 GHz"},
        {"kind": VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept", "verdict": "match"},
        {"kind": COVERAGE, "agent_id": "discovery", "text": "Path A ran; 2 vendors swept."},
        {"kind": AGENT_FINISHED, "agent_id": "discovery", "subtype": "success", "num_turns": 10, "tokens": 1000},
        {"kind": AGENT_FINISHED, "agent_id": "verify[M1]", "subtype": "success", "num_turns": 3, "tokens": 200},
    ]
    md = render_summary(events)

    assert "**Candidates found:** 2" in md
    assert "**Rejected:** 2" in md                    # one site-screen + one verify
    assert "**Sites/sources visited:** 2" in md       # everything.rf + the datasheet
    assert "1,200 tokens | 13 turns" in md            # summed from agent_finished
    assert "NF 4.2 > 1.5" in md                        # site-screen reason
    assert "freq band does not contain 2-6 GHz" in md  # verify reason
    assert "Path A ran; 2 vendors swept." in md        # coverage verbatim


def test_finish_writes_summary_file(tmp_path):
    logger = RunLogger(str(tmp_path))
    logger.emit({"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1", "manufacturer": "Y"})
    path = logger.finish()
    assert path is not None
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "**Candidates found:** 1" in text


# --- Resume support: outcome classification, spec_text, reused --------------


def test_classify_verify_outcome_maps_status_and_reason():
    assert classify_verify_outcome("kept", None) == OUTCOME_KEPT
    # Infrastructure failures -> retried on resume.
    assert classify_verify_outcome(
        "rejected", "insufficient verification: only 2/4, Gemini not available"
    ) == OUTCOME_FAILED_INFRA
    assert classify_verify_outcome(
        "rejected", "verify failed (error/rate-limit)"
    ) == OUTCOME_FAILED_INFRA
    # Genuine spec mismatches -> final.
    assert classify_verify_outcome(
        "rejected", "band does not contain 2-6 GHz"
    ) == OUTCOME_REJECTED_MISMATCH
    assert classify_verify_outcome("rejected", "no qualifying match") == OUTCOME_REJECTED_MISMATCH


def test_run_started_persists_spec_text(tmp_path):
    # The logger passes arbitrary fields through, so spec_text lands in the file.
    logger = RunLogger(str(tmp_path))
    logger.emit({"kind": RUN_STARTED, "agent_id": "run", "spec_text": "Component type: amplifier"})
    logger.close()
    obj = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert obj["spec_text"] == "Component type: amplifier"


def test_reused_flag_is_persisted(tmp_path):
    logger = RunLogger(str(tmp_path))
    logger.emit({
        "kind": VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept",
        "model": "M1", "outcome": OUTCOME_KEPT, "reused": True,
    })
    logger.close()
    obj = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert obj["reused"] is True and obj["outcome"] == OUTCOME_KEPT


def test_summary_counts_reused_and_marks_entries():
    events = [
        {"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M1",
         "manufacturer": "BeRex", "reused": True},           # carried over
        {"kind": CANDIDATE_FOUND, "agent_id": "discovery", "model": "M2", "manufacturer": "X"},
        {"kind": VERIFY_RESULT, "agent_id": "verify[M1]", "status": "kept",
         "verdict": "match", "outcome": OUTCOME_KEPT, "reused": True},
        {"kind": VERIFY_RESULT, "agent_id": "verify[M3]", "status": "rejected",
         "reason": "gain too low", "outcome": OUTCOME_REJECTED_MISMATCH, "reused": True},
    ]
    md = render_summary(events)
    assert "**Candidates found:** 2" in md                    # reused counts too
    assert "**Reused from prior runs:** 3" in md              # 2 candidates + 1 kept + 1 reject = 3 flagged...
    # (M1 candidate, M1 kept, M3 reject) all carry reused -> 3
    assert "M1 (BeRex) (reused)" in md                        # candidate marked
    assert "gain too low | verify[M3] (reused)" in md         # rejection marked
