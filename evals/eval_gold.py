"""Deterministic gold evaluator for the LLM datasheet parameter-extraction path.

A companion to ``eval_datasheet.py``.  That one uses a STRONGER model as the
judge (ground truth on the fly, no hand-labelling).  This one is the opposite
trade-off: you label the correct values ONCE per datasheet (because you have
verified those specific datasheets by hand), and every run checks the extraction
against them DETERMINISTICALLY -- no judge model, no cost, no non-determinism in
the scoring, identical result every time.

The extraction itself still runs the REAL model that ``rf_finder.config``
selects (that is the thing under test); only the SCORING is deterministic.

Two checks per case:

  1. Structure (script, cheap) -- reused verbatim from ``eval_datasheet``: valid
     JSON, exactly the requested keys, six-field contract with the right types.

  2. Gold (script, deterministic) -- for each parameter you can assert only the
     fields you care about:
       - numeric fields (min/typ/max) are compared NUMERICALLY, so 9 == 9.00;
       - unit / condition / string ``value`` are compared NORMALISED
         (case-insensitive, whitespace collapsed);
       - a list ``value`` is compared as a numeric multiset ([3,5,8] == [8,5,3]);
       - an expected value of ``None`` asserts the extractor returned null
         (the datasheet genuinely does not state that parameter).
     Fields you do NOT put in the gold are not checked.

Each run ends with a SUMMARY line per case and exits non-zero if any case fails
(bad JSON, wrong structure, or any gold mismatch) -- so it can run as an
automated regression gate.

Usage:
    python evals/eval_gold.py

Requirements: the extraction provider configured in ``rf_finder.config`` must be
reachable (Ollama running for ``local``, or ``GEMINI_API_KEY`` set for
``gemini``).  No judge provider is needed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from rf_finder.config import DATASHEET_MODEL, DATASHEET_PROVIDER
from rf_finder.datasheet import datasheet_text_from_pdf, extract_rf_parameters
from rf_finder.datasheet.extractor import _get_runtime

# Reuse the SAME structural contract check and value formatter the judge-based
# evaluator uses, so the two tools agree on shape and rendering.
from evals.eval_datasheet import check_structure, format_value, _num

HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdfs"


# One record per component.  ``expected`` is the hand-verified gold: a partial
# spec per parameter listing ONLY the fields to assert (or ``None`` to assert
# the parameter is absent from the datasheet).
GOLD_CASES = [
    {
        "part": "CMPA1E1F060D",
        "pdf": PDF_DIR / "cmpa1e1f060d.pdf",
        "requested_parameters": ["SIZE", "IM3", "Voltage"],
        "expected": {
            "SIZE": {"value": "4530 µm x 6090 µm (+0/-50 µm)"},
            "IM3": {"max": -25, "unit": "dBc"},
            "Voltage": {"typ": 28, "unit": "V"},
        },
    },
]


# ---------------------------------------------------------------------------
# Deterministic gold comparison
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = ("min", "typ", "max")


def _norm(s) -> str:
    """Normalise a string for comparison: casefold + collapse whitespace."""
    return " ".join(str(s).split()).casefold()


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num_eq(a, b) -> bool:
    return _is_num(a) and _is_num(b) and abs(float(a) - float(b)) < 1e-6


def _value_eq(exp, act) -> bool:
    """Compare a ``value`` field: numeric, list-as-multiset, or normalised str."""
    if _is_num(exp) and _is_num(act):
        return _num_eq(exp, act)
    if isinstance(exp, list) or isinstance(act, list):
        ex = sorted(exp) if isinstance(exp, list) else [exp]
        ac = sorted(act) if isinstance(act, list) else [act]
        return len(ex) == len(ac) and all(
            _num_eq(a, b) if _is_num(a) and _is_num(b) else _norm(a) == _norm(b)
            for a, b in zip(ex, ac)
        )
    return _norm(exp) == _norm(act)


def _field_eq(field: str, exp, act) -> bool:
    """Deterministic per-field equality, dispatched by field name."""
    if exp is None:
        return act is None
    if act is None:
        return False
    if field in _NUMERIC_FIELDS:
        return _num_eq(exp, act)
    if field == "value":
        return _value_eq(exp, act)
    # unit / condition -- normalised string compare
    return _norm(exp) == _norm(act)


def check_gold(expected: dict, actual: dict) -> list[dict]:
    """Compare an extraction against the gold; return one row per checked field.

    ``expected`` maps a parameter name to either a partial spec (dict of the
    fields to assert) or ``None`` (assert the extractor found nothing).  Each
    returned row is ``{param, field, expected, actual, ok}``.
    """
    rows: list[dict] = []
    for name, exp_spec in expected.items():
        act_spec = actual.get(name)
        if exp_spec is None:
            # Assert the parameter is absent (extractor returned null).
            rows.append({
                "param": name, "field": "(absent)",
                "expected": None, "actual": act_spec,
                "ok": act_spec is None,
            })
            continue
        for field, exp_val in exp_spec.items():
            act_val = act_spec.get(field) if isinstance(act_spec, dict) else None
            rows.append({
                "param": name, "field": field,
                "expected": exp_val, "actual": act_val,
                "ok": _field_eq(field, exp_val, act_val),
            })
    return rows


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------

def _cell(v) -> str:
    """Render an expected/actual value for the table."""
    if v is None:
        return "—"
    if _is_num(v):
        return _num(v)
    return str(v)


def run_case(case: dict, runtime) -> dict:
    part = case["part"]
    requested = case["requested_parameters"]
    expected = case["expected"]
    print(f"\n{f' {part} ':═^70}")

    text = datasheet_text_from_pdf(str(case["pdf"]))

    summary = {
        "part": part, "extract_ok": False, "structure_ok": False,
        "gold_ok": False, "gold_fail": 0, "none_count": 0,
    }

    # --- extraction (timed) ------------------------------------------------
    t0 = time.perf_counter()
    try:
        extracted = extract_rf_parameters(text, requested, runtime=runtime)
        extract_error = None
    except ValueError as e:        # the model's reply was not valid JSON
        extracted, extract_error = None, f"invalid JSON: {e}"
    except RuntimeError as e:      # the provider run itself failed
        extracted, extract_error = None, f"provider failure: {e}"
    latency = time.perf_counter() - t0

    if extracted is None:
        print(f"datasheet   {len(text):,} chars")
        print(f"extraction  ✗ FAILED in {latency:.1f}s — {extract_error}")
        return summary

    summary["extract_ok"] = True
    none_count = sum(1 for v in extracted.values() if v is None)
    summary["none_count"] = none_count
    print(
        f"datasheet   {len(text):,} chars · extraction {latency:.1f}s · "
        f"None-rate {none_count}/{len(requested)}"
    )

    # --- check 1: structure ------------------------------------------------
    problems = check_structure(extracted, requested)
    summary["structure_ok"] = not problems
    print(f"structure   {'✓ PASS' if not problems else '✗ FAIL'}")
    for p in problems:
        print(f"      └ {p}")

    # --- check 2: deterministic gold ---------------------------------------
    rows = check_gold(expected, extracted)
    fails = [r for r in rows if not r["ok"]]
    summary["gold_fail"] = len(fails)
    summary["gold_ok"] = not fails
    print(f"gold        {'✓ PASS' if not fails else f'✗ FAIL ({len(fails)} mismatch)'}")

    # --- table: expected vs actual per checked field -----------------------
    pw = max([len(r["param"]) for r in rows] + [9])
    fw = max([len(r["field"]) for r in rows] + [5])
    print(f"\n  {'parameter':<{pw}}  {'field':<{fw}}  {'expected':<26}  {'actual':<26}  ok")
    for r in rows:
        mark = "✓" if r["ok"] else "✗"
        exp, act = _cell(r["expected"]), _cell(r["actual"])
        print(f"  {r['param']:<{pw}}  {r['field']:<{fw}}  {exp:<26.26}  {act:<26.26}  {mark}")
    # Full expected/actual for any mismatch (untruncated), so a fail is legible.
    for r in fails:
        print(f"      └ {r['param']}.{r['field']}: expected {r['expected']!r}, got {r['actual']!r}")

    return summary


def main() -> None:
    # Datasheet text and model output carry non-ASCII (e.g. "°C", "µm"); force
    # UTF-8 stdout so they print cleanly on a Windows console (cp1252).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print(f"extraction model: {DATASHEET_PROVIDER} / {DATASHEET_MODEL}")
    print("scoring         : deterministic gold (no judge)")

    runtime = _get_runtime()
    summaries = [run_case(case, runtime) for case in GOLD_CASES]

    # --- overall summary + exit code ---------------------------------------
    print(f"\n{' SUMMARY ':═^70}")
    failed = 0
    partw = max([len(s["part"]) for s in summaries] + [4])
    for s in summaries:
        case_failed = (
            not s["extract_ok"]
            or not s["structure_ok"]
            or not s["gold_ok"]
        )
        if case_failed:
            failed += 1
        verdict = "✗ FAIL" if case_failed else "✓ PASS"
        structure = "✓" if s["structure_ok"] else "✗"
        gold = "✓" if s["gold_ok"] else f"✗ {s['gold_fail']}"
        print(
            f"  {verdict}  {s['part']:<{partw}}  structure {structure}  "
            f"gold {gold}  None {s['none_count']}"
        )
    print(f"\n  {len(summaries) - failed} / {len(summaries)} cases passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
