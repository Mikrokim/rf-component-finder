## Why

The only way to use the tool is the interactive terminal (`python -m rf_finder`), which asks for the component type and every constraint one `input()` prompt at a time and prints results as plain text. That is fine for a developer but awkward for a non-technical client. The search logic is already GUI-ready — `collect(schema, answers=...)` exposes a non-interactive `answers` dict seam — so a graphical form can wrap the existing pipeline.

## What Changes

- **New desktop GUI** (`rf_finder/ui/gui.py`), runnable via `python -m rf_finder.ui.gui`, presenting the same search as a Tkinter window instead of terminal prompts. English UI.
- **Extract a shared headless search core** so the GUI and CLI run the *same* search implementation. The adapter loop + `verify` + match/partial/fail sort currently inline in `main()` is pulled into a terminal-free module `rf_finder/search.py` (`search_and_verify(spec, *, on_source=None) -> list[VerifiedCandidate]`); `main()` calls it and keeps its `print` wrapping, and the GUI calls the identical helper and renders a table. The GUI cannot drift from the CLI because it *is* the CLI's search.
- **Form**: a component-type dropdown (from ontology `COMPONENTS`) that rebuilds the fields when changed; per field a min/max pair (range/`contains`/`between`/`min`/`max`) or a single value entry (scalar `eq`), plus a unit dropdown. Entries are gathered into the `answers` dict.
- **Results**: a `ttkbootstrap`-themed table showing **only the matching components** (`partial`/`fail` screened out), capped at a configurable `max_results` (default 10) with a "top N of M" note; double-clicking a row opens the datasheet url.
- **Input validation**: numeric-only entries; a `contains` field requires both bounds before searching (instead of `collect` silently dropping a half-entered range).
- **Configurable result cap** shared by both front-ends: `max_results` (default 10) read from `config.yaml` via a new `load_max_results()`. The CLI `match` group is capped by it too, so the two surfaces agree.
- **Complete, derived unit selectors**: each parameter's accepted `units` are derived from the conversion engine (`units_for`) instead of a hand-maintained list, so the form offers *every* convertible unit — `freq_range` gains `kHz`/`Hz`, `IP3` gains `W`/`mW`.
- **Responsiveness**: the search runs on a background thread and hands results back through a `queue.Queue` drained by a periodic poll, so Tk stays single-threaded and the window never freezes; a `collect` `ValueError` is shown in a dialog.

## Capabilities

### New Capabilities
- `desktop-gui`: A Tkinter desktop window that wraps the existing form → search → verify flow — the component-type-driven form, collection into a `QuerySpec` via the existing `answers` seam, background-threaded search over the shared core, and a matches-only results table with browser deep-links and input validation.

### Modified Capabilities
- `cli-result-output`: The CLI's `match` group is now capped at the configurable `max_results` (default 10) rather than a hardcoded 20, printing a "top N of M" note when truncated — so the terminal and the GUI show the same number of matching results.
- `parameter-ontology`: Each parameter's `units` list is now derived from the conversion engine (`units_for`) rather than hand-maintained, so it offers every convertible unit (`freq_range` → `["GHz","MHz","kHz","Hz"]`, `IP3` → `["dBm","W","mW"]`). Canonical-first ordering is preserved.

## Impact

- **New code:** `rf_finder/search.py` (the shared headless core), `rf_finder/ui/__init__.py`, and `rf_finder/ui/gui.py`.
- **Refactor:** the adapter-loop/verify/sort core moves out of `main()` (`rf_finder/__main__.py`) into `search_and_verify`; `main()` now calls it and keeps its `print` output. Both front-ends import the one helper.
- **Config:** `rf_finder/config.py` gains `load_max_results()` (+ `DEFAULT_MAX_RESULTS`) reading a top-level `max_results` from `config.yaml`; both front-ends load it at startup.
- **Ontology:** `rf_finder/ontology/units.py` gains `units_for(canonical)`; `rf_finder/ontology/parameters.py` derives each `ParamDef`'s `units` from its canonical unit. Converters and comparison rules unchanged.
- **Dependencies:** one new — `ttkbootstrap` (modern themed Tkinter widgets), added to `pyproject.toml`, plus an `rf-finder-gui` console script. Adapters fetch live (no cache on this branch).
- **Out of scope:** 2D Size (length × width), which needs adapter rework and belongs with future datasheet-extraction work; showing `partial`/`fail` in the GUI (matches-only is deliberate).
