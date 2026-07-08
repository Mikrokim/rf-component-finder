## Why

Today the only way to use the tool is the interactive terminal flow (`python -m rf_finder`), which asks for the component type and every constraint one `input()` prompt at a time and prints results as plain text. That is fine for a developer but awkward for a non-technical client: there is no way to see all fields at once, revise an earlier answer, or browse results. The search logic is already GUI-ready — `collect(schema, answers=...)` exposes a non-interactive `answers` dict seam — so a graphical form can wrap the existing pipeline without touching it.

## What Changes

- **New desktop GUI** (`rf_finder/ui/gui.py`), runnable via `python -m rf_finder.ui.gui`, that presents the same search as a Tkinter window instead of terminal prompts. English UI.
- The window **reuses the existing pipeline unchanged**: `build_form` for the fields, `collect(schema, answers=...)` for the `QuerySpec`, and the same `cache.configure(load_cache_config())` setup as `run_search`.
- **Extract a shared headless search core** so the GUI and CLI run the *same* search implementation. The adapter loop + `verify` + match/partial/fail sort currently embedded in `run_search` is pulled into a terminal-free helper (`search_and_verify(provider, spec) -> list[VerifiedCandidate]`); `run_search` calls it and keeps its `print` wrapping, and the GUI calls the identical helper and renders a table. This is an internal refactor: the CLI's observable terminal output is unchanged.
- **Form**: a component-type dropdown (from ontology `COMPONENTS`) that rebuilds the fields when changed; per field a min/max pair (range/`contains`/`between`/`min`/`max`) or a single value entry (scalar `eq`), plus a unit dropdown. Entries are gathered into the `answers` dict (`<name>.min` / `.max` / `.unit` / `.value`).
- **Results**: a sorted, color-coded table (match → partial → fail) with columns model, manufacturer, verdicts, url; double-clicking a row opens the url in the browser.
- **Responsiveness**: the search runs on a background thread with a loading state so the window never freezes during the multi-second fetch; a `collect` `ValueError` (bad unit, min > max) is shown in a dialog instead of crashing.

## Capabilities

### New Capabilities
- `desktop-gui`: A Tkinter desktop window that wraps the existing form → search → verify flow — the component-type-driven form built from the ontology, collection into a `QuerySpec` via the existing `answers` seam, background-threaded search, and a color-coded results table with browser deep-links. Purely an alternative presentation surface; it adds no new search, parsing, or ranking behavior.

### Modified Capabilities
<!-- None at the spec level. Extracting `search_and_verify` out of `run_search` is a
     non-behavioral refactor: the cli-result-output terminal behavior is unchanged, so no
     requirement of structured-form-input or cli-result-output changes. -->

## Impact

- **New code:** `rf_finder/ui/__init__.py` and `rf_finder/ui/gui.py`. No changes to adapters, ontology, form, verifier, or cache.
- **Refactor (behavior-preserving):** `rf_finder/__main__.py` gains `search_and_verify(provider, spec)` extracted from `run_search`; `run_search` now calls it and keeps its existing `print` output verbatim. The GUI imports the same helper, guaranteeing one physical search implementation shared by both front-ends.
- **Dependencies:** none new — Tkinter (`tkinter` / `tkinter.ttk`) is in the Python standard library; `webbrowser` (stdlib) for the row deep-link.
- **Entry point:** a second, additive way to run the tool (`python -m rf_finder.ui.gui`); the existing `python -m rf_finder` CLI keeps identical behavior.
- **Out of scope:** the manual `refresh` command inside the GUI, packaging into an `.exe`/installer, and any change to adapter/ontology/verifier behavior.
