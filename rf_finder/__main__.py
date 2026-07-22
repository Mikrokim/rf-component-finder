"""CLI entry point: run form → search → report (REQ-1.1, REQ-5).

The form and the result rendering live here; the actual search flow (adapters +
verify + datasheet enrichment + the two gates) is delegated to
``rf_finder.pipeline.run_pipeline`` so the CLI and the desktop GUI
(``rf_finder.ui.gui``) share one implementation.

The response-cache feature adds only: a provider configured up front (``main``),
a per-source snapshot-age note and a bounded join of background revalidations
(both via ``rf_finder.cli``), and a manual ``refresh`` subcommand
(``rf_finder.cli.run_refresh``).

  python -m rf_finder                     interactive cache-first search
  python -m rf_finder refresh [--adapter NAME]
                                          manual cache warm/refresh (never scheduled)
"""

from __future__ import annotations

import argparse
import sys

def run_search(provider) -> None:
    from rf_finder.form import build_form, collect
    from rf_finder.search import _sources_for
    from rf_finder.pipeline import run_pipeline
    from rf_finder.config import load_max_results
    from rf_finder import cli   # cache-feature helpers (snapshot note, join)

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
            print(f"  • {adapter.manufacturer}: 0 candidates{cli._snapshot_note(provider, adapter.manufacturer)}")
        else:  # "ok"
            print(f"  • {adapter.manufacturer}: {len(payload)} candidates{cli._snapshot_note(provider, adapter.manufacturer)}")

    verified = run_pipeline(spec, on_source=_note)

    if not verified:
        print("No matching components.")
        cli._join_cache(provider)
        return

    # ── 3. Output — the pipeline returns only accepted candidates, tagged
    #        match or not-verified, and already ordered match first. ───────────
    matches      = [v for v in verified if v.overall == "match"]
    not_verified = [v for v in verified if v.overall == "not-verified"]

    print(f"\n{'─'*60}")
    print(f"  match: {len(matches)}   not-verified: {len(not_verified)}")
    print(f"{'─'*60}\n")

    _LABEL = {"match": "MATCH       ", "not-verified": "NOT-VERIFIED"}
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

    if not_verified:
        print(
            f"── NOT-VERIFIED ({len(not_verified)}) — "
            "site parameters pass; the datasheet could not be accessed to confirm the rest ──"
        )
        _show(not_verified)
        print()

    cli._join_cache(provider)


def main(argv: list[str] | None = None) -> None:
    from rf_finder import http, cli
    from rf_finder.config import load_cache_config

    parser = argparse.ArgumentParser(
        prog="rf_finder", description="RF component finder (cache-first)."
    )
    sub = parser.add_subparsers(dest="command")
    refresh_p = sub.add_parser(
        "refresh", help="Re-fetch and store every source's pages (manual)."
    )
    refresh_p.add_argument(
        "--adapter", metavar="NAME", default=None,
        help="Refresh only this manufacturer (default: all).",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    provider = http.configure(load_cache_config())
    if args.command == "refresh":
        cli.run_refresh(provider, args.adapter)
    else:
        run_search(provider)


if __name__ == "__main__":
    main()
