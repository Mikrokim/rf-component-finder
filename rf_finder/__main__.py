"""CLI entry point: run form → search → report (REQ-1.1, REQ-5).

# TODO(T12): replace with full CLI wire-up (flags, per-adapter error isolation,
#             proper Reporter) once T11 and T12 are implemented.
"""

from __future__ import annotations


def main() -> None:
    from rf_finder.adapters.minicircuits import MiniCircuitsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.macom import MacomAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.analogdevices import AnalogDevicesAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.ums import UmsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.threerwave import ThreeRWaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.base import ADAPTERS
    from rf_finder.form import build_form, collect
    from rf_finder.verifier import verify

    # ── 1. Form ──────────────────────────────────────────────────────────────
    print("\n=== RF Component Finder ===\n")
    component_type = input("Component type [amplifier]: ").strip() or "amplifier"

    try:
        schema = build_form(component_type)
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"\nFill in constraints for '{component_type}' (leave blank to skip):\n")
    spec = collect(schema)

    print("\n--- Search parameters ---")
    print(f"  Component: {spec.component_type}")
    for c in spec.constraints:
        if c.range is not None:
            lo, hi = c.range
            if c.comparison == "between" and lo == float("-inf") and hi == float("inf"):
                rng = "any"
            elif c.comparison == "between" and hi == float("inf"):
                rng = f"≥ {lo}"
            elif c.comparison == "between" and lo == float("-inf"):
                rng = f"≤ {hi}"
            else:
                rng = f"{lo}–{hi}"
            print(f"  {c.canonical_name}: {rng} {c.unit}  [{c.comparison}]")
        else:
            print(f"  {c.canonical_name}: {c.value} {c.unit}  [{c.comparison}]")

    if not spec.constraints:
        print("  (no filters — returning all results)")

    # ── 2. Search ─────────────────────────────────────────────────────────────
    sources = [a for a in ADAPTERS.values() if spec.component_type in a.supported_components]
    names = ", ".join(a.manufacturer for a in sources) or "(none)"
    print(f"\nFetching from {len(sources)} source(s): {names}… (this may take a few seconds)\n")

    candidates = []
    for adapter in sources:
        try:
            found = adapter.search(spec)
            candidates.extend(found)
            print(f"  • {adapter.manufacturer}: {len(found)} candidates")
        except Exception as e:
            print(f"  [!] {adapter.manufacturer}: {e}")

    if not candidates:
        print("No candidates returned.")
        return

    print(f"Retrieved {len(candidates)} raw candidates.")

    # ── 3. Verify ─────────────────────────────────────────────────────────────
    verified = [verify(spec, c) for c in candidates]

    # ── 4. Simple output ──────────────────────────────────────────────────────
    order = {"match": 0, "partial": 1, "fail": 2}
    verified.sort(key=lambda v: order.get(v.overall, 9))

    matches  = [v for v in verified if v.overall == "match"]
    partials = [v for v in verified if v.overall == "partial"]
    fails    = [v for v in verified if v.overall == "fail"]

    print(f"\n{'─'*60}")
    print(f"  match: {len(matches)}   partial: {len(partials)}   fail: {len(fails)}")
    print(f"{'─'*60}\n")

    _LABEL = {"match": "MATCH  ", "partial": "PARTIAL", "fail": "FAIL   "}
    _STATUS = {"PASS": "✓", "FAIL": "✗", "UNKNOWN": "?"}

    def _show(group: list, limit: int = 20) -> None:
        for v in group[:limit]:
            c = v.candidate
            verdict_str = "  ".join(
                f"{vd.canonical_name}:{_STATUS.get(vd.status, '?')}"
                for vd in v.verdicts
            )
            print(f"  [{_LABEL[v.overall]}] {c.model:<22} {verdict_str}")
            print(f"           {c.url}")

    if matches:
        print(f"── MATCHES ({len(matches)}) ──")
        _show(matches)
        print()

    if partials:
        print(f"── PARTIAL ({len(partials)}) ──")
        _show(partials)
        print()

    if not matches and not partials:
        print("No matching or partial-match components found.\n")

    if fails:
        show_fails = input(f"Show {len(fails)} non-matching results? [y/N]: ").strip().lower()
        if show_fails == "y":
            print()
            _show(fails, limit=50)
            print()


if __name__ == "__main__":
    main()
