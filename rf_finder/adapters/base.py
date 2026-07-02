"""Adapter ABC, ADAPTERS self-registration registry, and AdapterError (REQ-3.1, NFR-4)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from rf_finder.adapters.datasheet import parse_params
from rf_finder.models import Candidate, QuerySpec


class AdapterError(Exception):
    """Raised by an adapter on retrieval failure. Carries context for the reporter."""

    def __init__(self, manufacturer: str, context: str, cause: Exception | None = None):
        self.manufacturer = manufacturer
        self.context = context
        self.cause = cause
        super().__init__(
            f"[{manufacturer}] {context}" + (f": {cause}" if cause else "")
        )


class Adapter(ABC):
    manufacturer: str           # class-level attribute, e.g. "Mini-Circuits"
    supported_components: list[str]  # e.g. ["amplifier"]

    # Canonical parameters this adapter can ONLY obtain from a datasheet (not its
    # HTML tables).  Empty = no datasheet tier.  A specific adapter overrides this
    # one declaration; the generic needs_datasheet / enrich below build on it, so
    # nothing here is tied to any particular parameter.
    datasheet_params: frozenset[str] = frozenset()

    @abstractmethod
    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Search for components matching spec. Raise AdapterError on failure."""
        ...

    def needs_datasheet(self, spec: QuerySpec) -> bool:
        """Return True if *spec* constrains a parameter this adapter can only get
        from a datasheet — i.e. the orchestrator should run the enrich phase.

        Generic: each adapter declares *which* params are datasheet-only via
        ``datasheet_params``; the check itself is identical for everyone.
        """
        required = {c.canonical_name for c in spec.constraints}
        return bool(required & self.datasheet_params)

    def enrich(self, candidate: Candidate, needed: set[str]) -> Candidate:
        """Fill *needed* datasheet-only params from this adapter's datasheet.

        Generic template:
          1. keep only the params this adapter sources from a datasheet,
          2. pull the datasheet text via the ``_datasheet_text`` hook,
          3. parse it with the shared pattern engine, and
          4. merge any new values — never overwriting values already found in
             the HTML table — raising the candidate's ``source`` to ``datasheet``.

        A no-op for adapters without a datasheet tier (empty ``datasheet_params``
        or ``_datasheet_text`` returning None), so callers invoke it uniformly.
        """
        targets = needed & self.datasheet_params
        if not targets:
            return candidate

        text = self._datasheet_text(candidate)
        if not text:
            return candidate

        additions = {
            name: value
            for name, value in parse_params(text, targets).items()
            if name not in candidate.raw_params
        }
        if not additions:
            return candidate

        return replace(
            candidate,
            raw_params={**candidate.raw_params, **additions},
            source="datasheet",
        )

    def _datasheet_text(self, candidate: Candidate) -> str | None:
        """Hook: return this candidate's datasheet text, or None if unavailable.

        Default None (no datasheet tier).  An adapter with a datasheet overrides
        this to locate, download, and extract its PDF.
        """
        return None


# Self-registration registry
ADAPTERS: dict[str, "Adapter"] = {}  # keyed by manufacturer name


def register(cls):
    """Class decorator: registers an Adapter subclass in ADAPTERS by its manufacturer."""
    ADAPTERS[cls.manufacturer] = cls()
    return cls
