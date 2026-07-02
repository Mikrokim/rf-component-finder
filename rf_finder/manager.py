"""Search orchestration layer — the *manager* (design.md §6.5).

Owns the end-to-end flow for one query: run each applicable adapter's search,
recover datasheet-only parameters where doing so can complete a match, and
verify.  This is the single place that depends on BOTH the adapters (data
access) and the Verifier (comparison), so neither of those layers depends on
the other — the adapter no longer reaches "up" to the Verifier just to target
its own enrichment.  ``__main__`` stays a thin CLI that delegates here.
"""

from __future__ import annotations

from rf_finder.adapters.base import Adapter
from rf_finder.models import Candidate, QuerySpec, VerifiedCandidate
from rf_finder.verifier import verify


class SearchManager:
    """Runs adapters, datasheet-enriches, and verifies for one ``QuerySpec``."""

    def __init__(self, adapters: list[Adapter]) -> None:
        self._adapters = adapters

    def run(self, spec: QuerySpec) -> tuple[list[VerifiedCandidate], list[str]]:
        """Search every applicable adapter, enrich, and verify.

        Returns ``(verified, errors)``: ``errors`` collects per-adapter failures
        so one manufacturer going down doesn't sink the whole run (NFR-4).
        """
        verified: list[VerifiedCandidate] = []
        errors: list[str] = []

        for adapter in self._adapters:
            if spec.component_type not in adapter.supported_components:
                continue
            try:
                candidates = adapter.search(spec)
            except Exception as exc:  # AdapterError or unexpected — isolate it
                errors.append(f"{adapter.manufacturer}: {exc}")
                continue
            candidates = self._enrich(adapter, spec, candidates)
            verified.extend(verify(spec, c) for c in candidates)

        return verified, errors

    def _enrich(
        self, adapter: Adapter, spec: QuerySpec, candidates: list[Candidate]
    ) -> list[Candidate]:
        """Datasheet-enrich (in place) the candidates whose only remaining gap is
        a datasheet-only parameter, and return the list.

        A no-op unless *spec* constrains a datasheet param.  Targeting uses the
        Verifier (the manufacturer sites cannot range-filter), so a datasheet is
        pulled only for a candidate that already PASSes every other required
        parameter — i.e. enrichment can turn it into a full match.  All
        candidates are returned (near-misses are never dropped); only some are
        enriched.

        The adapter supplies the *capability* (``needs_datasheet`` / ``enrich`` /
        ``datasheet_params``); the manager owns the *decision* of when to use it.
        """
        if not adapter.needs_datasheet(spec):
            return candidates

        for i, candidate in enumerate(candidates):
            result = verify(spec, candidate)
            if result.overall != "partial":
                continue  # full match needs nothing; a fail can't be rescued
            unknown = {v.canonical_name for v in result.verdicts if v.status == "UNKNOWN"}
            if unknown and unknown <= adapter.datasheet_params:
                candidates[i] = adapter.enrich(candidate, unknown)

        return candidates
