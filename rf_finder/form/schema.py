"""Build ordered form fields for a component type from the ontology (REQ-1.2)."""

from __future__ import annotations

from dataclasses import dataclass

from rf_finder.ontology.components import COMPONENTS
from rf_finder.ontology.parameters import params_for


@dataclass(frozen=True)
class Field:
    canonical_name: str   # ontology key e.g. "freq_range"
    label: str            # display label from ontology
    comparison: str       # "min" / "max" / "contains" / "eq"
    canonical_unit: str   # e.g. "GHz"
    units: list[str]      # accepted units, canonical first


@dataclass(frozen=True)
class FormSchema:
    component_type: str
    fields: list[Field]


def build_form(component_type: str) -> FormSchema:
    """Return an ordered ``FormSchema`` for *component_type*.

    Fields are ordered: ``contains`` params first (e.g. freq_range), then
    scalar params (min/max/eq) in ontology iteration order.

    Raises
    ------
    ValueError
        If *component_type* is not in ``COMPONENTS``.
    """
    if component_type not in COMPONENTS:
        raise ValueError(
            f"Unknown component type: {component_type!r}. "
            f"Valid types: {sorted(COMPONENTS)}"
        )

    param_defs = params_for(component_type)

    contains_fields: list[Field] = []
    scalar_fields: list[Field] = []

    for name, param in param_defs.items():
        field = Field(
            canonical_name=name,
            label=param.label,
            comparison=param.comparison,
            canonical_unit=param.canonical_unit,
            units=param.units,
        )
        if param.comparison == "contains":
            contains_fields.append(field)
        else:
            scalar_fields.append(field)

    return FormSchema(
        component_type=component_type,
        fields=contains_fields + scalar_fields,
    )
