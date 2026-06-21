"""Adapter ABC, ADAPTERS self-registration registry, and AdapterError (REQ-3.1, NFR-4)."""

from abc import ABC, abstractmethod

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
