## Why

An AI Search run can fail partway through — most commonly when the Gemini datasheet-extraction key is unavailable, which makes every `rf-verify` call return "insufficient verification" even though discovery succeeded. Today the only recovery is to re-run the whole query from scratch, repeating the expensive discovery sweep and every datasheet read that already succeeded. Since each run is already recorded to `runs/<timestamp>/events.jsonl`, re-running the same query should be able to continue from where the prior run stopped instead of redoing settled work.

## What Changes

- Add a **resume** mode to the AI Search pipeline: when enabled, re-running the same query continues from prior runs' logs instead of starting fresh.
- Add a new environment switch **`RF_RESUME`** that gates *reading/resuming* only. It is fully independent of the existing `RF_LOG` (which gates *writing* logs and is untouched). When `RF_RESUME` is on but no matching logs exist, the run proceeds fresh with no error.
- Key each run by the form's deterministic `spec_text`, stored on the `RUN_STARTED` event, so the same filter resolves to the same query identity across runs.
- On resume, scan the **4 most-recent** `runs/` directories by timestamp and use only those whose stored `spec_text` matches the current query; older runs are ignored.
- Distinguish two failure cases via discovery's `AGENT_FINISHED` event:
  - **Discovery finished cleanly** → skip discovery entirely and load the candidate list from the log.
  - **Discovery fell mid-way** → re-run discovery in full (an LLM agent has no internal checkpoint) but seed the dedup set and prior verdicts so no already-settled candidate is re-verified.
- Reuse per-candidate verify results: a candidate whose prior outcome is **final** (`kept` / `rejected_mismatch`) is passed straight through; only candidates whose prior outcome was an **infrastructure failure** (`failed_infra` — Gemini unavailable / "insufficient verification" / rate-limit / error) are re-verified.
- Extend the run event model to carry the data resume needs: `spec_text` on `RUN_STARTED`, an `outcome` classification on `VERIFY_RESULT`, and a `reused` flag on events copied forward from a prior run.
- A resumed run creates its **own** new `runs/<timestamp>/` directory, seeded with the reused events (marked `reused: true`), so its `summary.md` is a complete whole covering both reused and freshly-executed work.

## Capabilities

### New Capabilities
- `ai-search-resume`: Continuation of an AI Search run from prior-run logs — the `RF_RESUME` switch and its independence from `RF_LOG`, the `spec_text` query key, the 4-run lookback window, the skip-discovery-vs-re-run decision keyed on discovery completion, per-candidate verify reuse keyed on the `outcome` classification, cross-run merge rules, and the self-contained seeded `runs/<timestamp>/` output. Also owns the event-model extensions this requires (`spec_text` on `RUN_STARTED`, `outcome` on `VERIFY_RESULT`, `reused` on seeded events), which build on the `ai-search-observability` event stream.

### Modified Capabilities
<!-- None in openspec/specs/. The event model this extends (RUN_STARTED, VERIFY_RESULT, AGENT_FINISHED) is defined by the ai-search-observability capability, which currently lives in the unarchived add-ai-search-run-logging change rather than in openspec/specs/. The additive field extensions are captured within the new ai-search-resume spec above and are compatible with that event stream. -->

## Impact

- **Code changed:** `rf_finder/agent/skill_runner.py` (conductor: read `RF_RESUME`, load resume state, store `spec_text` on `RUN_STARTED`, seed the dedup set + prior verdicts, skip discovery when clean, skip settled verifies, classify verify `outcome`, seed reused events); `rf_finder/agent/run_log.py` (`spec_text` on `RUN_STARTED`, `outcome` on `VERIFY_RESULT`, `reused` flag on events, `render_summary` handling of reused events).
- **New code:** `rf_finder/agent/resume.py` (find last 4 runs, parse `events.jsonl`, filter by `spec_text`, reconstruct candidates + verdicts, decide skip-discovery).
- **Config:** `.env` documents the new `RF_RESUME` switch alongside `RF_LOG`.
- **Tests:** new `tests/test_resume.py`; extensions to `tests/test_skill_runner.py` and `tests/test_run_log.py`.
- **Skills:** not touched. Classifying the "insufficient verification" case is done conductor-side by matching that marker text; a structured `outcome` field emitted by the `rf-verify` skill is recorded as optional future hardening only.
- **Not included (optional):** a GUI checkbox in `rf_finder/ui/gui.py` — the `RF_RESUME` env var is sufficient.
