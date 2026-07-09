"""CLI entry point: run form → search → report (REQ-1.1, REQ-5).

The form and the result rendering live here; the actual search (adapters +
verify + ranking) is delegated to ``rf_finder.search.search_and_verify`` so the
CLI and the desktop GUI (``rf_finder.ui.gui``) share one implementation.
"""

from __future__ import annotations


def main() -> None:
    from rf_finder.form import build_form, collect
    from rf_finder.search import _sources_for, search_and_verify
    from rf_finder.config import load_max_results

    max_results = load_max_results()

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

    # ── 2. Search + verify (shared headless core) ─────────────────────────────
    sources = _sources_for(spec)
    names = ", ".join(a.manufacturer for a in sources) or "(none)"
    print(f"\nFetching from {len(sources)} source(s): {names}… (this may take a few seconds)\n")

    def _note(outcome, adapter, payload):
        if outcome == "error":
            print(f"  [!] {adapter.manufacturer}: {payload}")
        elif outcome == "empty":
            print(f"  • {adapter.manufacturer}: 0 candidates")
        else:  # "ok"
            print(f"  • {adapter.manufacturer}: {len(payload)} candidates")

    verified = search_and_verify(spec, on_source=_note)

    if not verified:
        print("No candidates returned.")
        return

    print(f"Retrieved {len(verified)} raw candidates.")

    # ── 3. Output (already ranked match→partial→fail by the core) ──────────────
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
        _show(matches, max_results)
        if len(matches) > max_results:
            print(f"  … showing top {max_results} of {len(matches)} — refine the filters to narrow down")
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
