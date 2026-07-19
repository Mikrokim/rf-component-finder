"""Collect and validate form fields, convert to QuerySpec (REQ-1.1, REQ-1.4–1.7)."""

from __future__ import annotations

from rf_finder.models import ParamConstraint, QuerySpec
from rf_finder.form.schema import Field, FormSchema

#: Comparison rules collected as a (possibly one-sided) range in the form.
#: ``contains``/``between`` are inherently range-valued; ``min``/``max`` are
#: single-bound rules that we also collect as a range so the user may cap the
#: other side too (e.g. Psat between 20 and 30 dBm, or Gain ≤ 40 dB). ``contains``
#: keeps its own rule; everything else is emitted as a ``between`` constraint —
#: see :func:`_build_range_constraint`.
RANGE_COMPARISONS = ("contains", "between", "min", "max")


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
        - range field (``contains`` / ``between`` / ``min`` / ``max``) →
          ``"<canonical_name>.min"``, ``"<canonical_name>.max"``,
          ``"<canonical_name>.unit"`` (a ``min``/``max`` param may fill just one
          side — an omitted bound is left open)
        - scalar field (``eq``) → ``"<canonical_name>.value"``, ``"<canonical_name>.unit"``

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


def _resolve_unit(unit_str: str, field: Field) -> str:
    """Return the canonical unit when *unit_str* is empty, else validate it."""
    if not unit_str:
        return field.canonical_unit
    return _validate_unit(unit_str, field)


def _build_range_constraint(
    field: Field,
    min_str: str,
    max_str: str,
    unit_str: str,
) -> ParamConstraint | None:
    """Build a range ``ParamConstraint`` from raw min/max/unit strings.

    Shared by every range-collected comparison rule (see ``RANGE_COMPARISONS``):

    - ``contains`` band field (freq_range, Temperature): a partial range is
      meaningless, so both bounds must be present — otherwise the field is
      skipped.  Emitted as a ``contains`` constraint.
    - ``contains`` with ``single_value_ok`` (VDD): the user enters ONE value or
      a full range.  A lone entry is that single required voltage — the point
      ``(v, v)`` — never an open-ended range.  Emitted as ``contains``.
    - ``between`` / ``min`` / ``max``: either side may be omitted; an omitted
      ``min`` defaults to ``-inf`` and an omitted ``max`` to ``+inf`` (a one-
      sided range imposing no restriction on that side).  Emitted as
      ``between`` — a single-bound query is just a one-sided ``between``.

    Returns ``None`` when the field has no usable input and should be skipped
    (REQ-1.6).  Raises ``ValueError`` on a non-numeric bound, ``min > max``, or
    an invalid unit (REQ-1.7).
    """
    name = field.canonical_name

    if not min_str and not max_str:
        return None  # nothing entered → no constraint

    is_band_only = field.comparison == "contains" and not field.single_value_ok
    if is_band_only and (not min_str or not max_str):
        return None  # partial band for a band-only 'contains' field → skip

    def _num(text: str, side: str) -> float:
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{name}.{side}: {text!r} is not a valid number")

    if field.single_value_ok:
        # VDD: one entry → the point (v, v); both entries → the range (min, max).
        min_val = _num(min_str or max_str, "min")
        max_val = _num(max_str or min_str, "max")
    else:
        min_val = _num(min_str, "min") if min_str else float("-inf")
        max_val = _num(max_str, "max") if max_str else float("inf")

    if min_val > max_val:
        raise ValueError(
            f"{name}: min ({min_val}) must not be greater than max ({max_val})"
        )

    # A single-bound scalar (min/max) collected as a range is semantically a
    # ``between``; a ``contains`` field (a candidate that is itself a band, incl.
    # VDD) keeps its rule.
    emitted = "contains" if field.comparison == "contains" else "between"
    return ParamConstraint(
        canonical_name=name,
        comparison=emitted,
        value=None,
        range=(min_val, max_val),
        unit=_resolve_unit(unit_str, field),
    )


def _collect_from_answers(schema: FormSchema, answers: dict[str, str]) -> QuerySpec:
    constraints: list[ParamConstraint] = []

    for field in schema.fields:
        name = field.canonical_name

        if field.comparison in RANGE_COMPARISONS:
            constraint = _build_range_constraint(
                field,
                _get_answer(answers, f"{name}.min"),
                _get_answer(answers, f"{name}.max"),
                _get_answer(answers, f"{name}.unit"),
            )
            if constraint is not None:
                constraints.append(constraint)

        else:
            # scalar: eq (a single exact value)
            value_str = _get_answer(answers, f"{name}.value")
            if not value_str:
                continue

            try:
                scalar = float(value_str)
            except ValueError:
                raise ValueError(
                    f"{name}.value: {value_str!r} is not a valid number"
                )

            constraints.append(
                ParamConstraint(
                    canonical_name=name,
                    comparison=field.comparison,
                    value=scalar,
                    range=None,
                    unit=_resolve_unit(_get_answer(answers, f"{name}.unit"), field),
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

    def _select_unit(field: Field) -> str:
        """Return the chosen unit (canonical unless the user picks another)."""
        if _use_questionary and len(field.units) > 1:
            return questionary.select("  Unit:", choices=field.units).ask()
        return field.units[0]

    constraints: list[ParamConstraint] = []

    for field in schema.fields:
        name = field.canonical_name

        if field.comparison in RANGE_COMPARISONS:
            is_band_only = field.comparison == "contains" and not field.single_value_ok
            if field.single_value_ok:
                print(f"\n{field.label} (one value, or a range — enter min and max)")
            elif is_band_only:
                print(f"\n{field.label} (range)")
            else:
                print(f"\n{field.label} (range — leave a side blank for open-ended)")

            while True:
                min_raw = input(f"  Min ({field.units}): ").strip()
                max_raw = input(f"  Max ({field.units}): ").strip()

                # Nothing entered (or a partial band on a band-only field) → skip.
                if not min_raw and not max_raw:
                    break
                if is_band_only and (not min_raw or not max_raw):
                    break

                try:
                    if field.single_value_ok:
                        # One entry → the point (v, v); both → the range.
                        min_val = float(min_raw or max_raw)
                        max_val = float(max_raw or min_raw)
                    else:
                        min_val = float(min_raw) if min_raw else float("-inf")
                        max_val = float(max_raw) if max_raw else float("inf")
                except ValueError:
                    print("  Please enter numeric values.")
                    continue

                if min_val > max_val:
                    print("  Min must not be greater than max.")
                    continue

                # A min/max scalar collected as a range is a one-sided
                # ``between``; a ``contains`` field (incl. VDD) keeps its rule.
                emitted = "contains" if field.comparison == "contains" else "between"
                constraints.append(
                    ParamConstraint(
                        canonical_name=name,
                        comparison=emitted,
                        value=None,
                        range=(min_val, max_val),
                        unit=_select_unit(field),
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

            constraints.append(
                ParamConstraint(
                    canonical_name=name,
                    comparison=field.comparison,
                    value=scalar,
                    range=None,
                    unit=_select_unit(field),
                )
            )

    return QuerySpec(component_type=schema.component_type, constraints=constraints)
