## Why

Today the only way to use the tool is the interactive terminal flow (`python -m rf_finder`), which asks for the component type and every constraint one `input()` prompt at a time and prints results as plain text. That is fine for a developer but awkward for a non-technical client: there is no way to see all fields at once, revise an earlier answer, or browse results. The search logic is already GUI-ready — `collect(schema, answers=...)` exposes a non-interactive `answers` dict seam — so a graphical form can wrap the existing pipeline without touching it.

## What Changes

- **New desktop GUI** (`rf_finder/ui/gui.py`), runnable via `python -m rf_finder.ui.gui`, that presents the same search as a Tkinter window instead of terminal prompts. English UI.
- The window **reuses the existing pipeline unchanged**: `build_form` for the fields, `collect(schema, answers=...)` for the `QuerySpec`, and the same `cache.configure(load_cache_config())` setup as `run_search`.
- **Extract a shared headless search core** so the GUI and CLI run the *same* search implementation. The adapter loop + `verify` + match/partial/fail sort currently embedded in `run_search` is pulled into a terminal-free module `rf_finder/search.py` (`search_and_verify(spec, *, on_source=None) -> list[VerifiedCandidate]`); `run_search` calls it and keeps its `print` wrapping, and the GUI calls the identical helper and renders a table. This is an internal refactor: the CLI's observable terminal output is unchanged.
- **Form**: a component-type dropdown (from ontology `COMPONENTS`) that rebuilds the fields when changed; per field a min/max pair (range/`contains`/`between`/`min`/`max`) or a single value entry (scalar `eq`), plus a unit dropdown. Entries are gathered into the `answers` dict (`<name>.min` / `.max` / `.unit` / `.value`).
- **Results**: a table (built with `ttkbootstrap` for a modern look) showing **only the matching components** — `partial`/`fail` candidates are screened out — capped at a configurable `max_results` (default 10) with a "top N of M" note when more exist; columns model, manufacturer, verdicts, url; double-clicking a row opens the url in the browser.
- **Shared, configurable result cap**: a `max_results` setting (default 10) is read from `config.yaml` via a new `load_max_results()` in `rf_finder/config.py`, and applied by **both** front-ends. The CLI's `match` group is now capped by it (was a hardcoded 20) with the same "top N of M" note, so the two surfaces stay consistent and the client can retune the cap without code changes.
- **Complete, derived unit selectors**: each parameter's accepted `units` are now derived from the conversion engine (`units_for` in `rf_finder/ontology/units.py`) instead of a hand-maintained list, so the form offers *every* convertible unit — `freq_range` gains `kHz`/`Hz`, `IP3` gains `W`/`mW`. This benefits the CLI form too, not just the GUI.
- **Responsiveness**: the search runs on a background thread with a loading state so the window never freezes during the multi-second fetch; a `collect` `ValueError` (bad unit, min > max) is shown in a dialog instead of crashing.

## Capabilities

### New Capabilities
- `desktop-gui`: A Tkinter desktop window that wraps the existing form → search → verify flow — the component-type-driven form built from the ontology, collection into a `QuerySpec` via the existing `answers` seam, background-threaded search, and a color-coded results table with browser deep-links. Purely an alternative presentation surface; it adds no new search, parsing, or ranking behavior.

### Modified Capabilities
- `cli-result-output`: The CLI's `match` group is now capped at the configurable `max_results` (default 10) rather than a hardcoded 20, and prints a "top N of M" note when truncated — so the terminal and the GUI show the same number of matching results. (Extracting `search_and_verify` out of `run_search` remains a non-behavioral refactor; only this display cap changes.)
- `parameter-ontology`: Each parameter's `units` list is now derived from the conversion engine (`units_for`) rather than hand-maintained, so it offers every convertible unit — `freq_range` becomes `["GHz","MHz","kHz","Hz"]` and `IP3` becomes `["dBm","W","mW"]`. Canonical-first ordering is preserved.

## Impact

- **New code:** `rf_finder/search.py` (the shared headless core), `rf_finder/ui/__init__.py`, and `rf_finder/ui/gui.py`. No changes to adapters, ontology, form, verifier, or cache.
- **Refactor (behavior-preserving):** the adapter-loop/verify/sort core moves out of `run_search` into `rf_finder/search.py` as `search_and_verify(spec, *, on_source=None)` (along with `_load_adapters`/`_sources_for`); `run_search` now calls it and keeps its existing `print` output verbatim, and `cli.py`'s `_load_adapters` import repoints to `rf_finder.search`. The GUI imports the same helper, guaranteeing one physical search implementation shared by both front-ends.
- **Config:** `rf_finder/config.py` gains `load_max_results()` (+ `DEFAULT_MAX_RESULTS`) reading a top-level `max_results` from `config.yaml`; both front-ends load it at startup. `CacheConfig` is untouched — the display cap is deliberately not a cache setting.
- **Ontology:** `rf_finder/ontology/units.py` gains a `units_for(canonical)` registry (`_CANONICAL_UNITS`), and `rf_finder/ontology/parameters.py` builds each `ParamDef` through a `_param` factory that derives `units` from `canonical_unit`. Converters and comparison rules are unchanged; only the widened `units` lists (`freq_range`, `IP3`) are observable.
- **Dependencies:** one new — `ttkbootstrap` (modern themed Tkinter widgets, pip-installable, pulls in `pillow`), added to `pyproject.toml`. Tkinter itself and `webbrowser` remain stdlib. A second console-script entry `rf-finder-gui = rf_finder.ui.gui:main` is added for convenience.
- **Entry point:** a second, additive way to run the tool (`python -m rf_finder.ui.gui`); the existing `python -m rf_finder` CLI keeps identical behavior.
- **Out of scope:** the manual `refresh` command inside the GUI, packaging into an `.exe`/installer, and any change to adapter/ontology/verifier behavior.
