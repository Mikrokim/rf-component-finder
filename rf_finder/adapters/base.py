"""Adapter ABC, ADAPTERS self-registration registry, and AdapterError (REQ-3.1, NFR-4)."""

from abc import ABC, abstractmethod

from rf_finder.models import Candidate, QuerySpec, RawValue


def drop_paramless(candidates: list[Candidate]) -> list[Candidate]:
    """Drop candidates that carry no parametric data at all.

    A candidate with an empty ``raw_params`` gives the Verifier nothing to check,
    so it can only ever surface as an all-UNKNOWN ``partial`` — pure noise rather
    than a usable result (typically non-RF parts mis-listed in a manufacturer's
    amplifier table). Every adapter filters these out at the ``search()``
    boundary.

    Note: this filter is intentionally silent. The dropped parts are unusable, so
    they are not reported. Trade-off: a future source schema change that breaks
    parsing would yield empty ``raw_params`` for every row and surface as "no
    results" rather than a parse error (see t8-plan.md risk R2).
    """
    return [c for c in candidates if c.raw_params]


def freq_range_from_bandwidth(bandwidth_hz: float) -> RawValue:
    """Express a single -3 dB Bandwidth value as a canonical frequency range.

    A part that specifies only a *bandwidth* (rather than a frequency-response
    band) is a DC-coupled wideband amplifier: it operates from DC (0 Hz) up to
    that bandwidth, so the bandwidth maps to a ``(0, bandwidth)`` ``freq_range``.

    Shared by every adapter: each adapter identifies its own site-specific
    bandwidth column/field, then calls this to convert it to ``freq_range``.
    """
    return RawValue(value=(0.0, bandwidth_hz), unit="Hz")


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

    @abstractmethod
    def search(self, spec: QuerySpec) -> list[Candidate]:
        """Search for components matching spec. Raise AdapterError on failure."""
        ...


# Self-registration registry
ADAPTERS: dict[str, "Adapter"] = {}  # keyed by manufacturer name


def register(cls):
    """Class decorator: registers an Adapter subclass in ADAPTERS by its manufacturer."""
    ADAPTERS[cls.manufacturer] = cls()
    return cls
