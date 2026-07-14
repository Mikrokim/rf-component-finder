"""Evaluator for the LLM datasheet parameter-extraction path.

Run this occasionally to check that the LLM's analysis of a datasheet is
correct.  It is dev tooling, NOT part of the shipped `rf_finder` package and NOT
the MockProvider contract tests in `tests/` — this path runs the REAL model that
`rf_finder.config` selects (`DATASHEET_PROVIDER` / `DATASHEET_MODEL`).

Two checks per case:

  1. Structure (script, cheap, every run) — did the model return valid JSON,
     with exactly the requested keys, and does every FOUND parameter carry the
     six fields `{unit, min, typ, max, value, condition}` with the right types?
     `extract_rf_parameters` raises `ValueError` on invalid JSON, so "returns
     JSON" is measured by catching that instead of letting the run crash.

  1b. Grounding (script, cheap, every run) — a model-free hallucination guard:
     every number the extractor reported must appear among the datasheet's own
     numbers, else it is flagged.

  2. Judge (strong model, occasional) — hand the datasheet text plus the values
     the extractor produced to a STRONGER model and ask, per parameter: is the
     value correct for this datasheet, and is it grounded (does it actually
     appear in the text, i.e. not hallucinated)?  The judge is the ground truth,
     so no hand-labelled gold values are needed.

Also reported (cheap, provider-agnostic): wall-clock latency and the None-rate
(how many requested parameters came back null) — a proxy for context truncation.

Each run ends with a SUMMARY line per case and exits non-zero if any case fails
(bad JSON, wrong structure, or a judge flag) — so it can run as an automated
regression gate. Grounding is advisory: it WARNS but does not fail the gate,
since a number may be legitimate yet live only in a drawing the text extractor
misses.

Usage:
    python evals/eval_datasheet.py            # structure + judge
    python evals/eval_datasheet.py --no-judge # structure only (cheap run)

Requirements: the extraction provider configured in `rf_finder.config` must be
reachable (Ollama running for `local`, or `GEMINI_API_KEY` set for `gemini`),
and the judge provider below likewise.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from rf_finder.config import DATASHEET_MODEL, DATASHEET_PROVIDER
from rf_finder.datasheet import datasheet_text_from_pdf, extract_rf_parameters

# These are private helpers of the extractor, reused here on purpose: the
# evaluator wants the SAME JSON-recovery and runtime/provider wiring the real
# extraction path uses, and the SAME six-field contract it enforces.
from rf_finder.datasheet.extractor import (
    _SPEC_FIELDS,
    _extract_json_object,
    _get_runtime,
)

HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdfs"

# The judge should be a STRONGER model than the extractor.  It is selected here,
# independently of the extraction model (which comes from rf_finder.config).
JUDGE_PROVIDER = "gemini"
# An alias to the current latest Gemini Pro, on purpose: pinning an explicit
# version (e.g. "gemini-2.5-pro") 404s once Google retires it — "-latest"
# always resolves to the strongest available Pro.
JUDGE_MODEL = "gemini-pro-latest"


# One record per component.  No gold values: check 1 is structural and check 2
# uses the judge as ground truth, so a case only needs a PDF and the parameter
# names to request.
CASES = [
    {
        "part": "ADCA3270",
        "pdf": PDF_DIR / "adca3270.pdf",
        # size -> length + width; storage (not operating) temperature.
        "requested_parameters": ["storage_temperature", "length", "width"],
    },
    {
        "part": "GRF2111",
        "pdf": PDF_DIR / "grf2111.pdf",
        "requested_parameters": ["Operating Temperature", "VOLTAGE", "size"],
    },
    {
        "part": "HMC952ALP5GE",
        "pdf": PDF_DIR / "hmc952alp5ge.pdf",
        "requested_parameters": ["operating Temperature", "msl", "size"],
    },
    {
        "part": "AM06013033WM-QN5-R",
        "pdf": PDF_DIR / "am06013033wm.pdf",
        "requested_parameters": ["voltage", "size", "Storage temperature"],
    },
]


# ---------------------------------------------------------------------------
# Check 1 — structure (cheap, every run)
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = ("min", "typ", "max")


def check_structure(extracted: dict, requested: list[str]) -> list[str]:
    """Return a list of structural problems; empty list means the shape is good.

    Verifies exactly the requested keys are present, and that every FOUND
    parameter (a dict, not ``None``) carries exactly the six contract fields
    with the right JSON types.  A ``None`` value is a valid "not found" shape.
    """
    problems: list[str] = []

    if set(extracted) != set(requested):
        problems.append(
            f"keys {sorted(extracted)} != requested {sorted(requested)}"
        )

    for name, spec in extracted.items():
        if spec is None:
            continue  # "not found" — a valid shape
        if not isinstance(spec, dict):
            problems.append(f"{name}: not an object (got {type(spec).__name__})")
            continue
        if set(spec) != set(_SPEC_FIELDS):
            problems.append(
                f"{name}: fields {sorted(spec)} != {sorted(_SPEC_FIELDS)}"
            )
        for field in _NUMERIC_FIELDS:
            v = spec.get(field)
            # bool is an int subclass — exclude it explicitly.
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                problems.append(f"{name}.{field}: expected number|null, got {v!r}")
        for field in ("unit", "condition"):
            v = spec.get(field)
            if v is not None and not isinstance(v, str):
                problems.append(f"{name}.{field}: expected str|null, got {v!r}")
        val = spec.get("value")
        if val is not None and not isinstance(val, (str, int, float, list)):
            problems.append(
                f"{name}.value: expected str|number|list|null, got {val!r}"
            )

    return problems


# ---------------------------------------------------------------------------
# Check 1b — deterministic grounding (cheap, model-free hallucination guard)
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


def check_grounding(spec, datasheet_text: str) -> list[float]:
    """Numbers the extractor reported that do NOT appear in the datasheet text.

    A cheap, model-free hallucination guard complementing the judge: every
    number in a found spec (min/typ/max, and numbers inside `value`) should be
    findable among the datasheet's own numbers. Compared by magnitude, so 9.0
    matches "9.00" and a Unicode-minus "−40" in the PDF still matches -40.
    Heuristic: it ignores thousands separators, so e.g. 1,218 may read as a
    false miss.
    """
    if not isinstance(spec, dict):
        return []
    wanted: list[float] = []
    for field in ("min", "typ", "max"):
        v = spec.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            wanted.append(float(v))
    val = spec.get("value")
    if val is not None:
        wanted.extend(float(m) for m in _NUM_RE.findall(str(val)))
    if not wanted:
        return []
    in_text = {abs(float(m)) for m in _NUM_RE.findall(datasheet_text)}
    return [n for n in wanted if not any(abs(abs(n) - t) < 1e-6 for t in in_text)]


# ---------------------------------------------------------------------------
# Check 2 — judge (strong model, occasional)
# ---------------------------------------------------------------------------

JUDGE_INSTRUCTION = """\
Return only a valid JSON object. No markdown, no prose, no ``` fences.
You are a strict verifier of RF datasheet parameter extraction.

The Context has two keys:
  - "datasheet": the full raw text of a component datasheet.
  - "extracted": an object mapping each requested parameter name to the value
    another model extracted for it — either an object
    {unit, min, typ, max, value, condition}, or null if that model claimed the
    datasheet does not state the parameter.

For EACH key in "extracted", judge the extraction against the datasheet text
ONLY. Return a JSON object with the SAME keys, each mapping to:
  {
    "correct":  <true|false>,   // Does the extracted value match what the
                                // datasheet states for THIS parameter — the
                                // right variant and the right numbers/value?
                                // (The UNIT is judged separately in "unit_ok".)
                                // If the extraction is null, "correct" is
                                // true ONLY when the datasheet genuinely does
                                // not state this parameter.
    "grounded": <true|false>,   // Do the extracted numbers / text actually
                                // appear in the datasheet (not invented)? For a
                                // null extraction, "grounded" is true.
    "unit_ok":  <true|false>,   // Is the unit PRESENT and correct for this value
                                // (dB for gain, dBm for P1dB/IP3/power, GHz or
                                // MHz for frequency, °C for temperature, mm for
                                // size, V for supply)? A NUMERIC value (min/typ/
                                // max) with a MISSING or wrong unit in the "unit"
                                // field is unit_ok=false. BUT for a CATEGORICAL
                                // value carried as a string (e.g. size
                                // "1.5 x 1.5 mm", package), a unit embedded IN
                                // the value string counts as present, so unit_ok
                                // is true even when the separate "unit" field is
                                // null. For a null extraction or a genuinely
                                // unit-less value (e.g. MSL), unit_ok is true.
    "expected": "<what the datasheet actually states for it, or 'absent'>",
    "reason":   "<one short sentence>"
  }

Be strict about variants: storage temperature and operating temperature are
DIFFERENT parameters — do not accept one for the other. "length" and "width"
are the two body dimensions (e.g. a "9.00 mm x 8.00 mm" package: length 9.00 mm,
width 8.00 mm).

Return only JSON.
"""


def judge_values(datasheet_text: str, extracted: dict, runtime) -> tuple[dict | None, str | None]:
    """Ask the strong judge model to verify each extracted value.

    Returns ``(verdicts, None)`` on success or ``(None, error)`` when the judge
    run fails or its reply is not valid JSON.
    """
    result = runtime.run(
        instruction=JUDGE_INSTRUCTION,
        provider=JUDGE_PROVIDER,
        model=JUDGE_MODEL,
        input={"datasheet": datasheet_text, "extracted": extracted},
    )
    if not result.success:
        return None, result.error
    raw = _extract_json_object(result.output)
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"judge returned invalid JSON: {e}\nRaw:\n{raw}"


# ---------------------------------------------------------------------------
# CLI formatting helpers
# ---------------------------------------------------------------------------

def _num(n) -> str:
    """Compact number: 9.0 -> '9', 2.7 -> '2.7', -40.0 -> '-40'."""
    return f"{n:g}" if isinstance(n, (int, float)) and not isinstance(n, bool) else str(n)


def format_value(spec) -> str:
    """Render an extracted spec as a short human-readable value for the CLI."""
    if not isinstance(spec, dict):
        return "—"
    unit, val = spec.get("unit"), spec.get("value")
    lo, typ, hi = spec.get("min"), spec.get("typ"), spec.get("max")
    if val not in (None, "", []):
        s = str(val)                          # categorical string / list
        if unit and unit not in s:            # append a separate unit (e.g. "1.5 x 1.5" + "mm")
            s = f"{s} {unit}"
        return s
    tail = f" {unit}" if unit else ""
    if lo is not None and hi is not None:
        return f"{_num(lo)} … {_num(hi)}{tail}"
    if typ is not None:
        return f"{_num(typ)}{tail}"
    if lo is not None:
        return f"≥ {_num(lo)}{tail}"
    if hi is not None:
        return f"≤ {_num(hi)}{tail}"
    return "—"


def _mark(flag) -> str:
    """✓ for True, ✗ for False, · for a missing verdict."""
    return {True: "✓", False: "✗"}.get(flag, "·")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_case(case: dict, runtime, do_judge: bool) -> dict:
    part = case["part"]
    requested = case["requested_parameters"]
    print(f"\n{f' {part} ':═^58}")

    text = datasheet_text_from_pdf(str(case["pdf"]))

    summary = {
        "part": part, "requested": len(requested),
        "extract_ok": False, "structure_ok": False,
        "none_count": 0, "grounding_missing": 0,
        "judge_ran": False, "judge_flags": 0,
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

    # --- check 1b: deterministic grounding (per parameter) -----------------
    grounding = {n: check_grounding(extracted.get(n), text) for n in requested}
    summary["grounding_missing"] = sum(len(m) for m in grounding.values())
    if not summary["grounding_missing"]:
        print("grounding   ✓ PASS")
    else:
        print("grounding   ⚠ WARN  (number not in text — inferred, or in a drawing)")
        for name, miss in grounding.items():
            if miss:
                print(f"      └ {name}: {miss}")

    # --- check 2: judge ----------------------------------------------------
    verdicts = None
    if do_judge:
        verdicts, judge_error = judge_values(text, extracted, runtime)
        if verdicts is None:
            print(f"judge       UNAVAILABLE — {judge_error}")
        else:
            summary["judge_ran"] = True
            print(f"judge · {JUDGE_MODEL}")

    # --- parameter table ---------------------------------------------------
    namew = max([len(n) for n in requested] + [9])
    print(f"\n  {'parameter':<{namew}}  {'value':<18} {'grnd':^4} {'corr':^4} {'unit':^4}")
    flagged: list[tuple[str, str]] = []
    for name in requested:
        value = format_value(extracted.get(name))
        grnd = "✓" if not grounding[name] else "⚠"
        v = verdicts.get(name) if isinstance(verdicts, dict) else None
        if isinstance(v, dict):
            corr, unit = _mark(v.get("correct")), _mark(v.get("unit_ok"))
            if v.get("correct") is False or v.get("unit_ok") is False:
                summary["judge_flags"] += 1
                flagged.append((name, v.get("reason") or ""))
        else:
            corr = unit = "·"
        print(f"  {name:<{namew}}  {value:<18} {grnd:^4} {corr:^4} {unit:^4}")
    for name, reason in flagged:
        print(f"      └ {name}: {reason}")

    return summary


def main() -> None:
    # Datasheet text and model output carry non-ASCII (e.g. "°C", em-dashes);
    # force UTF-8 stdout so they print cleanly on a Windows console (cp1252).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    do_judge = "--no-judge" not in sys.argv
    print(f"extraction model: {DATASHEET_PROVIDER} / {DATASHEET_MODEL}")
    if do_judge:
        print(f"judge model     : {JUDGE_PROVIDER} / {JUDGE_MODEL}")
    else:
        print("judge model     : (skipped: --no-judge)")

    runtime = _get_runtime()
    summaries = [run_case(case, runtime, do_judge) for case in CASES]

    # --- overall summary + exit code ---------------------------------------
    # Grounding is advisory (it can false-positive on numbers that live only in a
    # drawing pdfplumber can't read), so it warns but does NOT fail the gate —
    # only extraction, structure, and judge flags do.
    print(f"\n{' SUMMARY ':═^58}")
    failed = 0
    partw = max([len(s["part"]) for s in summaries] + [4])
    for s in summaries:
        case_failed = (
            not s["extract_ok"]
            or not s["structure_ok"]
            or s["judge_flags"] > 0
        )
        if case_failed:
            failed += 1
        verdict = "✗ FAIL" if case_failed else "✓ PASS"
        structure = "✓" if s["structure_ok"] else "✗"
        grounding = "✓" if s["grounding_missing"] == 0 else "⚠"
        judge = f"judge {s['judge_flags']} flags" if s["judge_ran"] else "judge n/a"
        print(
            f"  {verdict}  {s['part']:<{partw}}  structure {structure}  "
            f"grounding {grounding}  {judge}  None {s['none_count']}/{s['requested']}"
        )
    print(f"\n  {len(summaries) - failed} / {len(summaries)} cases passed.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
