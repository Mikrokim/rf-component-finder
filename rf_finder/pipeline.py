"""Management layer — the datasheet-orchestration pipeline (design.md D1–D10).

``run_pipeline`` is the single owner of the search flow. It wires the otherwise
decoupled adapter, verifier, and datasheet layers together and enforces a
two-gate policy over ``verifier.verify()`` verdicts:

    1. retrieve   — every supporting adapter lists every part it has, keeping
                    each candidate's producing adapter so later stages know whom
                    to ask (``(adapter, candidate)`` pairs).
    2. Gate 1     — ``verify()``; keep a candidate iff no verdict is ``FAIL``
                    (every site-provided parameter passes; ``UNKNOWN`` deferred).
    3. resolve    — for a Gate 1 survivor that still has an ``UNKNOWN`` requested
                    parameter, ask its adapter for the datasheet link.
    4. enrich     — fetch that datasheet, extract ONLY the missing parameters,
                    and merge them into a copy (datasheet never overwrites table).
    5. Gate 2     — ``verify()`` again; tag ``match`` / ``not-verified`` / drop.

Reuse and boundaries:
- ``verify()`` is the ONLY comparator; each gate is policy over its verdicts.
- The layer holds NO per-site knowledge — *where* a datasheet link lives is the
  adapter's business (``resolve_datasheet_url``); the pipeline only asks.
- Resilience mirrors ``search_and_verify`` (D6): one adapter raising, one PDF
  failing, or one extraction erroring never aborts the run.
- The ``httpx`` / ``pdfplumber`` / LLM imports stay lazy (inside ``_enrich``), so
  importing this module is free and the table-only path needs neither the ``llm``
  extra nor the network when nothing must be enriched.

Result: a ``list[VerifiedCandidate]`` whose ``overall`` carries the pipeline
outcome — ``match`` or ``not-verified`` (D9). The datasheet link and ``source``
are internal; the front-ends (D9) surface only model / manufacturer / url /
outcome.
"""

from __future__ import annotations

import dataclasses
import logging

from rf_finder.models import Candidate, QuerySpec, VerifiedCandidate
from rf_finder.search import _sources_for
from rf_finder.verifier import verify

_log = logging.getLogger(__name__)

# D8: a not-verified candidate is shown only when at least this share of the
# user's requested parameters verify as PASS.
_COVERAGE_THRESHOLD = 0.80


def run_pipeline(spec: QuerySpec, *, on_source=None) -> list[VerifiedCandidate]:
    """Run the four-stage flow and return accepted candidates, match first.

    ``on_source(outcome, adapter, payload)`` is the same progress hook
    ``search_and_verify`` defines — called once per source during retrieval with
    ``outcome`` in ``{"error", "empty", "ok"}``.

    Each returned ``VerifiedCandidate`` carries the Gate 2 verdicts and, in
    ``overall``, the pipeline result outcome ``"match"`` or ``"not-verified"``.
    """
    results: list[VerifiedCandidate] = []
    for adapter, cand in _retrieve(spec, on_source):
        try:
            graded = _grade(spec, adapter, cand)
        except Exception:
            # D6: one candidate must never abort the run. Retrieval, resolution
            # and enrichment are each contained on their own; this guard covers
            # the grading itself — verify() can raise on a value/unit pair the
            # ontology cannot convert, and that is one candidate's problem.
            _log.warning("skipping %s (%s): grading raised", cand.model, cand.manufacturer,
                         exc_info=True)
            continue
        if graded is not None:
            results.append(graded)

    # Match first, then not-verified (stable — discovery order kept within group).
    order = {"match": 0, "not-verified": 1}
    results.sort(key=lambda v: order.get(v.overall, 9))
    return results


# ---------------------------------------------------------------------------
# Stage 1 — retrieve (keeps the producing adapter per candidate)
# ---------------------------------------------------------------------------

def _retrieve(spec: QuerySpec, on_source) -> list[tuple[object, Candidate]]:
    """Gather ``(adapter, candidate)`` pairs; one bad source is skipped (D6)."""
    pairs: list[tuple[object, Candidate]] = []
    for adapter in _sources_for(spec):
        try:
            found = adapter.search(spec)
        except Exception as exc:  # one bad source must not stop the others
            if on_source is not None:
                on_source("error", adapter, exc)
            continue
        if not found:
            if on_source is not None:
                on_source("empty", adapter, None)
            continue
        pairs.extend((adapter, c) for c in found)
        if on_source is not None:
            on_source("ok", adapter, found)
    return pairs


# ---------------------------------------------------------------------------
# Per-candidate: Gate 1 → resolve → enrich → Gate 2
# ---------------------------------------------------------------------------

def _grade(spec: QuerySpec, adapter, cand: Candidate) -> VerifiedCandidate | None:
    """Run one candidate through the gates; return its result or ``None`` (dropped)."""
    # --- Gate 1: drop on any FAIL; UNKNOWN (site-missing) is deferred. ---
    v1 = verify(spec, cand)
    if any(vd.status == "FAIL" for vd in v1.verdicts):
        return None
    missing = [vd.canonical_name for vd in v1.verdicts if vd.status == "UNKNOWN"]

    # Nothing missing → already a full match. Resolve nothing, fetch nothing.
    if not missing:
        return _result(cand, v1.verdicts, "match")

    # --- Stage 3: resolve the link on demand (only for survivors needing it). ---
    resolved = _resolve(adapter, cand)
    cand = dataclasses.replace(cand, datasheet_url=resolved)

    # --- Stage 4: enrich from the datasheet (missing params only). ---
    cand, datasheet_accessible = _enrich(cand, missing)

    # --- Gate 2. ---
    return _gate2(spec, cand, datasheet_accessible)


def _resolve(adapter, cand: Candidate) -> str | None:
    """Ask the adapter for the datasheet link; contain a misbehaving adapter (D10).

    The contract says ``resolve_datasheet_url`` returns ``None`` rather than
    raising, but a per-candidate failure must never abort the run — so an
    accidental exception collapses to ``None`` ("no datasheet access" cond. 1).
    """
    try:
        return adapter.resolve_datasheet_url(cand)
    except Exception:
        return None


def _enrich(cand: Candidate, missing: list[str]) -> tuple[Candidate, bool]:
    """Fetch + extract the missing params; return ``(candidate, accessible)``.

    ``accessible`` is the D7 boolean: ``True`` only when the datasheet was
    fetched, parsed, AND the extractor ran. Any of the five "no access"
    conditions returns ``False`` and leaves the candidate unchanged. Imports are
    lazy so importing this module needs neither ``httpx``/``pdfplumber`` nor the
    ``llm`` extra.
    """
    if not cand.datasheet_url:
        return cand, False  # condition 1: no link after resolution

    try:
        from rf_finder.datasheet.extractor import extract_rf_parameters
        from rf_finder.datasheet.mapping import to_raw_params
        from rf_finder.datasheet.pdf import (
            DatasheetFetchError,
            datasheet_text_from_url,
        )
    except Exception:
        return cand, False  # condition 5: extractor / its deps unavailable

    try:
        text = datasheet_text_from_url(cand.datasheet_url)
    except DatasheetFetchError:
        return cand, False  # conditions 2/3/4: fetch / non-PDF / unparseable

    try:
        params = extract_rf_parameters(text, missing)
    except Exception:
        return cand, False  # condition 5: the extraction call errored

    # Accessed: fetched + parsed + extractor ran. Merge only the missing keys,
    # never overwriting a table value; tag the copy source="datasheet" (D4).
    datasheet_raw = to_raw_params(params)
    additions = {k: v for k, v in datasheet_raw.items() if k not in cand.raw_params}
    if additions:
        cand = dataclasses.replace(
            cand,
            raw_params={**cand.raw_params, **additions},
            source="datasheet",
        )
    return cand, True


def _gate2(
    spec: QuerySpec, cand: Candidate, datasheet_accessible: bool
) -> VerifiedCandidate | None:
    """Re-verify and assign match / not-verified / drop (D2, D7, D8)."""
    v = verify(spec, cand)
    statuses = [vd.status for vd in v.verdicts]

    if "FAIL" in statuses:
        return None  # a FAIL always drops, whatever else is unverified
    if "UNKNOWN" not in statuses:
        return _result(cand, v.verdicts, "match")

    # Some requested params are still UNKNOWN.
    if datasheet_accessible:
        # The datasheet was read but is silent on them → dropped (not not-verified).
        return None

    # Not accessible → the UNKNOWNs are datasheet-access failures → not-verified,
    # but only if the candidate clears the 80% pass-coverage bar (D8).
    total = len(spec.constraints)
    passed = sum(1 for vd in v.verdicts if vd.status == "PASS")
    coverage = (passed / total) if total else 0.0
    if coverage >= _COVERAGE_THRESHOLD:
        return _result(cand, v.verdicts, "not-verified")
    return None  # below coverage → dropped


def _result(cand: Candidate, verdicts, outcome: str) -> VerifiedCandidate:
    """Build the returned VerifiedCandidate carrying the pipeline *outcome*."""
    confidence = cand.source if cand.source in ("table", "datasheet") else "unknown"
    return VerifiedCandidate(
        candidate=cand,
        verdicts=verdicts,
        overall=outcome,
        confidence=confidence,
    )
