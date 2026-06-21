"""Component type registry: COMPONENTS dict and helper lookups (REQ-1.2, REQ-1.3)."""

from __future__ import annotations


COMPONENTS: dict[str, dict] = {
    "amplifier": {"label": "Amplifier"},
    # mixer, filter, attenuator ... added in later phases
}


def component_labels() -> dict[str, str]:
    """Return ``{canonical_name: label}`` for every registered component type."""
    return {key: val["label"] for key, val in COMPONENTS.items()}
