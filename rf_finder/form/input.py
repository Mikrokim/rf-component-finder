"""Collect and validate form fields, convert to QuerySpec (REQ-1.1, REQ-1.4–1.7)."""

from __future__ import annotations

from rf_finder.models import ParamConstraint, QuerySpec
from rf_finder.form.schema import Field, FormSchema


def collect(
    schema: FormSchema,
    *,
    answers: dict[str, str] | None = None,
) -> QuerySpec:
    """Collect form fields and return a ``QuerySpec``.

    Parameters
    ----------
    schema:
        The ``FormSchema`` returned by ``build_form``.
    answers:
        TTY seam for testing.  When provided, values are read from this dict
        instead of prompting the user interactively.

        Key conventions:
        - ``contains`` field  → ``"<canonical_name>.min"``, ``"<canonical_name>.max"``,
          ``"<canonical_name>.unit"``
        - scalar field        → ``"<canonical_name>.value"``, ``"<canonical_name>.unit"``

        Omit a key (or set its value to ``""``) to leave that field empty.

    Returns
    -------
    QuerySpec
        Only filled fields produce a ``ParamConstraint``; empty fields are
        skipped (REQ-1.6).

    Raises
    ------
    ValueError
        Non-numeric answer, range min > max, or unrecognised unit.
    """
    if answers is not None:
        return _collect_from_answers(schema, answers)
    return _collect_interactive(schema)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_answer(answers: dict[str, str], key: str) -> str:
    """Return the answer for *key*, defaulting to empty string."""
    return answers.get(key, "").strip()


def _validate_unit(unit_str: str, field: Field) -> str:
    """Return *unit_str* if it is in ``field.units``, else raise ``ValueError``."""
    if unit_str not in field.units:
        raise ValueError(
            f"Unit {unit_str!r} is not valid for {field.canonical_name!r}. "
            f"Accepted: {field.units}"
        )
    return unit_str


def _collect_from_answers(schema: FormSchema, answers: dict[str, str]) -> QuerySpec:
    constraints: list[ParamConstraint] = []

    for field in schema.fields:
        name = field.canonical_name

        if field.comparison == "contains":
            min_str = _get_answer(answers, f"{name}.min")
            max_str = _get_answer(answers, f"{name}.max")
            unit_str = _get_answer(answers, f"{name}.unit")

            # All three must be non-empty to create a constraint
            if not min_str and not max_str and not unit_str:
                continue
            # If some but not all are provided, still skip gracefully when empty
            if not min_str and not max_str:
                continue

            if not min_str or not max_str:
                # partial — treat as empty and skip
                continue

            try:
                min_val = float(min_str)
            except ValueError:
                raise ValueError(
                    f"{name}.min: {min_str!r} is not a valid number"
                )
            try:
                max_val = float(max_str)
            except ValueError:
                raise ValueError(
                    f"{name}.max: {max_str!r} is not a valid number"
                )

            if min_val > max_val:
                raise ValueError(
                    f"{name}: min ({min_val}) must not be greater than max ({max_val})"
                )

            # Unit: use canonical if not provided
            if not unit_str:
                unit_str = field.canonical_unit
            else:
                _validate_unit(unit_str, field)

            constraints.append(
                ParamConstraint(
                    canonical_name=name,
                    comparison="contains",
                    value=None,
                    range=(min_val, max_val),
                    unit=unit_str,
                )
            )

        else:
            # scalar: min / max / eq
            value_str = _get_answer(answers, f"{name}.value")
            unit_str = _get_answer(answers, f"{name}.unit")

            if not value_str:
                continue

            try:
                scalar = float(value_str)
            except ValueError:
                raise ValueError(
                    f"{name}.value: {value_str!r} is not a valid number"
                )

            if not unit_str:
                unit_str = field.canonical_unit
            else:
                _validate_unit(unit_str, field)

            constraints.append(
                ParamConstraint(
                    canonical_name=name,
                    comparison=field.comparison,
                    value=scalar,
                    range=None,
                    unit=unit_str,
                )
            )

    return QuerySpec(component_type=schema.component_type, constraints=constraints)


def _collect_interactive(schema: FormSchema) -> QuerySpec:
    """Prompt the user interactively via ``questionary`` (or plain ``input``)."""
    try:
        import questionary  # type: ignore[import]
        _use_questionary = True
    except ImportError:
        _use_questionary = False

    constraints: list[ParamConstraint] = []

    for field in schema.fields:
        name = field.canonical_name

        if field.comparison == "contains":
            print(f"\n{field.label} (range)")

            while True:
                min_raw = input(f"  Min ({field.units}): ").strip()
                if not min_raw:
                    break
                max_raw = input(f"  Max ({field.units}): ").strip()
                if not max_raw:
                    break

                try:
                    min_val = float(min_raw)
                    max_val = float(max_raw)
                except ValueError:
                    print("  Please enter numeric values.")
                    continue

                if min_val > max_val:
                    print("  Min must not be greater than max.")
                    continue

                # Unit selection
                if _use_questionary and len(field.units) > 1:
                    unit = questionary.select(
                        "  Unit:", choices=field.units
                    ).ask()
                else:
                    unit = field.units[0]  # default to canonical

                constraints.append(
                    ParamConstraint(
                        canonical_name=name,
                        comparison="contains",
                        value=None,
                        range=(min_val, max_val),
                        unit=unit,
                    )
                )
                break

        else:
            print(f"\n{field.label} (leave blank to skip)")
            value_raw = input(f"  Value ({field.units}): ").strip()
            if not value_raw:
                continue

            while True:
                try:
                    scalar = float(value_raw)
                    break
                except ValueError:
                    value_raw = input(
                        f"  Invalid. Re-enter value ({field.units}): "
                    ).strip()
                    if not value_raw:
                        scalar = None  # type: ignore[assignment]
                        break

            if scalar is None:
                continue

            if _use_questionary and len(field.units) > 1:
                unit = questionary.select("  Unit:", choices=field.units).ask()
            else:
                unit = field.units[0]

            constraints.append(
                ParamConstraint(
                    canonical_name=name,
                    comparison=field.comparison,
                    value=scalar,
                    range=None,
                    unit=unit,
                )
            )

    return QuerySpec(component_type=schema.component_type, constraints=constraints)
