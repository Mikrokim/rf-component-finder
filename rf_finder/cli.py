"""Response-cache feature glue for the CLI (NFR-1, NFR-2).

The pre-existing interactive search flow stays in ``__main__``; this module holds
only what the cache feature adds: the manual ``refresh`` command, the per-source
snapshot-age annotation, and the bounded join of background revalidations. The
original ``run_search`` calls the two small helpers here (``_snapshot_note``,
``_join_cache``) but otherwise is untouched.
"""

from __future__ import annotations


def _format_age(age_seconds: float | None) -> str:
    """Human snapshot age: ``just fetched`` / ``N hours ago`` / ``N days ago``."""
    if age_seconds is None:
        return "just fetched"
    if age_seconds < 3600:
        return "under an hour old"
    if age_seconds < 86_400:
        return f"{int(age_seconds // 3600)}h old"
    return f"{int(age_seconds // 86_400)}d old"


def _snapshot_note(provider, manufacturer: str) -> str:
    """A per-source cache-age suffix, flagging a served-stale copy when used."""
    age, stale = provider.served_summary(manufacturer)
    if stale:
        return f"  [⚠ served stale copy, {_format_age(age)}]"
    if age is None:
        return "  [fetched live]"
    return f"  [cache: {_format_age(age)}]"


def _join_cache(provider) -> None:
    """Wait (bounded) for background cache revalidations to settle."""
    print("\nUpdating cache…", flush=True)
    provider.join_revalidations()


# ---------------------------------------------------------------------------
# Refresh (manual, never scheduled)
# ---------------------------------------------------------------------------


def run_refresh(provider, adapter_name: str | None = None) -> None:
    """Force a live fetch + store for every page each adapter reads.

    Drives each adapter's own ``search()`` under refresh mode so every URL it
    traverses (including dynamically discovered ones) is re-fetched and stored.
    Errors are isolated per adapter: one failing source never stops the rest.
    """
    from rf_finder.models import QuerySpec
    from rf_finder.search import _load_adapters

    adapters = _load_adapters()
    selected = list(adapters.values())
    if adapter_name:
        selected = [
            a for a in selected
            if a.manufacturer.lower() == adapter_name.lower()
        ]
        if not selected:
            known = ", ".join(a.manufacturer for a in adapters.values())
            print(f"Unknown adapter '{adapter_name}'. Known: {known}")
            return

    print(f"\n=== Refreshing cache for {len(selected)} source(s) ===\n")
    provider.set_refresh_mode(True)
    try:
        for adapter in selected:
            component = next(iter(adapter.supported_components), "amplifier")
            spec = QuerySpec(component_type=component, constraints=[])
            try:
                found = adapter.search(spec)
                print(f"  • {adapter.manufacturer}: refreshed ({len(found)} candidates)")
            except Exception as e:
                print(f"  [!] {adapter.manufacturer}: failed — {e}")
    finally:
        provider.set_refresh_mode(False)

    _join_cache(provider)
