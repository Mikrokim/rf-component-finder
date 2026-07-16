## 1. Extract shared headless search core

- [x] 1.1 Create `rf_finder/search.py` and move `_load_adapters` into it; add `_sources_for(spec)` and `search_and_verify(spec, *, on_source=None) -> list[VerifiedCandidate]`: for each supporting adapter call `adapter.search(spec)` with per-source exception isolation, `verify(spec, candidate)` for each candidate, sort match→partial→fail (the existing `{match:0, partial:1, fail:2}` order), and report progress via the optional `on_source(outcome, adapter, payload)` hook. No `print`/`input`.
- [x] 1.2 Refactor `main()` in `rf_finder/__main__.py` to call `search_and_verify` (passing an `on_source` callback that prints the existing per-source lines) while keeping all its `print` output; the adapter imports move into `search.py`'s `_load_adapters`
- [x] 1.3 Run the test suite to confirm the refactor preserves the CLI output

## 2. Module scaffold

- [x] 2.1 Create `rf_finder/ui/__init__.py` (empty package marker)
- [x] 2.2 Create `rf_finder/ui/gui.py` with a `main()` entry point and a `if __name__ == "__main__": main()` guard so `python -m rf_finder.ui.gui` launches it
- [x] 2.3 In `main()`, build and run the Tk root window (no cache; adapters fetch live, like the CLI)

## 3. Ontology-driven form

- [x] 3.1 Add a component-type `ttk.Combobox` populated from `COMPONENTS`, defaulting to `amplifier`
- [x] 3.2 Implement `build_fields(component_type)` that calls `build_form(component_type)` and renders one input group per field, in order: min+max entries for range comparisons (`contains`/`between`/`min`/`max`), a single value entry for scalar `eq`
- [x] 3.3 For every field render a unit `ttk.Combobox` of `field.units` with `units[0]` (canonical) selected by default
- [x] 3.4 Store the widgets per field so their values can later be read out; rebuild (destroy + recreate) the field frame when the component-type selection changes, clearing prior values

## 4. Collect + search (background thread)

- [x] 4.1 Implement `build_answers()` that reads the widgets into a dict using the `collect` key convention (`<name>.min`/`.max`/`.unit`, `<name>.value`/`.unit`), omitting empty entries
- [x] 4.2 On Search: call `collect(schema, answers=build_answers())`; wrap in `try/except ValueError` and show the message via `messagebox.showerror`, leaving the form intact
- [x] 4.3 Run the search on a `threading.Thread` by calling the shared `search_and_verify(spec)` helper (same implementation the CLI uses)
- [x] 4.4 Disable the Search button and show a loading indication while a search is running; block starting a second concurrent search
- [x] 4.5 Hand results back to the UI thread via a `queue.Queue` drained by a periodic `root.after` poll (worker never touches Tk directly)

## 5. Results table (matches only)

- [x] 5.1 Add a `ttk.Treeview` with columns model, manufacturer, verdicts, url
- [x] 5.2 Show only `match` rows (screen out partial/fail) with a count of how many were hidden; tint match rows
- [x] 5.3 Bind `<Double-1>` to open the row's url with `webbrowser.open`
- [x] 5.4 When a search yields no `match` candidates, show an explicit "no matching components" indication (with the number screened) instead of an empty table
- [x] 5.5 Clear previous results at the start of each new search
- [x] 5.6 Cap the table at a configurable `max_results` (default 10) with a "top N of M" note; apply the same cap to the CLI's `match` group so both surfaces agree
- [x] 5.7 Add `load_max_results()` + `DEFAULT_MAX_RESULTS` to `rf_finder/config.py` (top-level `max_results` in `config.yaml`, validated positive int, default 10); both front-ends load it at startup; `tests/test_config.py` covers default/override/invalid

## 6. Styling

- [x] 6.1 Add the `ttkbootstrap` dependency to `pyproject.toml` (+ a `rf-finder-gui` console script); install it into the venv
- [x] 6.2 Theme the window with ttkbootstrap (`minty`): header + subtitle, filters/results grouped in `Labelframe`s, a large `success` Search button, styled Treeview
- [x] 6.3 Show every field at once with comfortable spacing — no inner form scroll (window sized to fit)

## 7. Input validation

- [x] 7.1 Numeric-only key validation on every value entry (digits / leading `-` / single `.`), so letters can't be typed
- [x] 7.2 Pre-search check: a `contains` field with exactly one of min/max filled shows an error and blocks the search (instead of `collect` silently dropping it); `between`/`min`/`max` may stay one-sided

## 8. Complete, derived unit selectors

- [x] 8.1 Add `units_for(canonical)` + the `_CANONICAL_UNITS` registry to `rf_finder/ontology/units.py` (frequency units derived from the conversion table; power/ratio listed; canonical first; unknown canonical → `[canonical]`)
- [x] 8.2 In `rf_finder/ontology/parameters.py`, build each `ParamDef` via a `_param` factory that derives `units` from `canonical_unit` (removing the hand-maintained lists); `freq_range` now offers `GHz/MHz/kHz/Hz`, `IP3` now offers `dBm/W/mW`
- [x] 8.3 Update `tests/test_ontology.py` for the derived lists (+ cover power params and no-converter params)

## 9. Verify

- [x] 9.1 Add headless unit tests (no Tk driving): `build_answers()` produces the expected key set (the `freq_range`/`P1dB` keystone); `search_and_verify` returns candidates ordered match→partial→fail; `_validate_numeric` accepts numbers / rejects letters; `_validate_form` flags a one-sided `contains` but not a one-sided `between` — `tests/test_search.py` + `tests/test_gui.py` + `tests/test_config.py`; full suite 426 passed
- [x] 9.2 Manually run `python -m rf_finder.ui.gui`: fill the amplifier form, run a search, confirm the table shows only matches, double-click opens the datasheet, a half-filled frequency range is rejected, and letters can't be typed  *(final user click-through)*
- [x] 9.3 Confirm `python -m rf_finder` (the existing CLI) still runs — output preserved; full suite green
