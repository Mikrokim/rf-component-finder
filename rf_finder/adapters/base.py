"""Adapter ABC, ADAPTERS self-registration registry, and AdapterError (REQ-3.1, NFR-4)."""

from abc import ABC, abstractmethod

from rf_finder.models import Candidate, QuerySpec, RawValue


# Secondary parameters: supply/physical/environmental specs that qualify a part
# but do not describe its RF performance. A candidate carrying ONLY these (e.g. a
# non-RF part that a vendor lists with a supply voltage but no freq/gain/etc.)
# cannot be evaluated as an amplifier, so it counts as having no usable data.
# ``Size`` is retained transitionally: the ontology now models physical size as
# two params (``length``/``width``), but the Marki/Microchip adapters still emit
# a single ``Size`` RawValue pending their rework, so it must stay classified as
# secondary here to keep ``drop_paramless`` from treating a size-only part as RF.
_SECONDARY_PARAMS = frozenset({"VDD", "length", "width", "Size", "MSL", "Temperature"})


def drop_paramless(candidates: list[Candidate]) -> list[Candidate]:
    """Drop candidates that carry no RF performance data.

    A candidate keeps only if it has at least one *primary* (RF) parameter —
    ``freq_range``, ``Gain``, ``NF``, ``P1dB``, ``Psat``, ``IP3``. One that has
    nothing, or only *secondary* params (``VDD``/``length``/``width``/``MSL``/``Temperature``;
    see ``_SECONDARY_PARAMS``), gives the Verifier no RF spec to check and can only
    surface as an all-UNKNOWN ``partial`` — pure noise rather than a usable result
    (typically non-RF parts mis-listed in a manufacturer's amplifier feed, e.g.
    ADI lists a supply voltage for such parts). Every adapter filters these out at
    the ``search()`` boundary.

    Note: this filter is intentionally silent. The dropped parts are unusable, so
    they are not reported. Trade-off: a future source schema change that breaks
    parsing would yield empty ``raw_params`` for every row and surface as "no
    results" rather than a parse error (see t8-plan.md risk R2).
    """
    return [c for c in candidates if set(c.raw_params) - _SECONDARY_PARAMS]


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
