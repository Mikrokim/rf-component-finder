"""CLI entry point: run form → search → report (REQ-1.1, REQ-5).

The interactive search flow below is the original CLI. The response-cache feature
adds only: a provider configured up front (``main``), a per-source snapshot-age
note and a bounded join of background revalidations (both via ``rf_finder.cli``),
and a manual ``refresh`` subcommand (``rf_finder.cli.run_refresh``).

  python -m rf_finder                     interactive cache-first search
  python -m rf_finder refresh [--adapter NAME]
                                          manual cache warm/refresh (never scheduled)
"""

from __future__ import annotations

import argparse
import sys


def _load_adapters():
    """Import every adapter module (triggers @register) and return the registry."""
    from rf_finder.adapters.minicircuits import MiniCircuitsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.amcomusa import AmcomUSAAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.analogdevices import AnalogDevicesAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.marki import MarkiMicrowaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.rwmmic import RwmmicAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.macom import MacomAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.ums import UmsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.threerwave import ThreeRWaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.microchip import MicrochipAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.guerrillarf import GuerrillaRFAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.vectrawave import VectraWaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.qorvo import QorvoAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.base import ADAPTERS

    return ADAPTERS


def run_search(provider) -> None:
    from rf_finder.form import build_form, collect
    from rf_finder.verifier import verify
    from rf_finder import cli   # cache-feature helpers (snapshot note, join)

    adapters = _load_adapters()

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
    sources = [a for a in adapters.values() if spec.component_type in a.supported_components]
    names = ", ".join(a.manufacturer for a in sources) or "(none)"
    print(f"\nFetching from {len(sources)} source(s): {names}… (this may take a few seconds)\n")

    candidates = []
    for adapter in sources:
        try:
            found = adapter.search(spec)
        except Exception as e:
            print(f"  [!] {adapter.manufacturer}: {e}")
            continue
        if not found:
            print(f"  – {adapter.manufacturer}: no data (source skipped){cli._snapshot_note(provider, adapter.manufacturer)}")
            continue
        candidates.extend(found)
        print(f"  • {adapter.manufacturer}: {len(found)} candidates{cli._snapshot_note(provider, adapter.manufacturer)}")

    if not candidates:
        print("No candidates returned.")
        cli._join_cache(provider)
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

    cli._join_cache(provider)


def main(argv: list[str] | None = None) -> None:
    from rf_finder import cache, cli
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

    provider = cache.configure(load_cache_config())
    if args.command == "refresh":
        cli.run_refresh(provider, args.adapter)
    else:
        run_search(provider)


if __name__ == "__main__":
    main()
