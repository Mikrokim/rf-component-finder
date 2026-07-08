## 1. Extract shared headless search core

- [ ] 1.1 In `rf_finder/__main__.py`, add `search_and_verify(provider, spec) -> list[VerifiedCandidate]`: select adapters whose `supported_components` include `spec.component_type`, call `adapter.search(spec)` per source with per-source exception isolation, `verify(spec, candidate)` for each candidate, and sort match→partial→fail (the existing `{match:0, partial:1, fail:2}` order). No `print`/`input`.
- [ ] 1.2 Refactor `run_search` to call `search_and_verify` for the work while keeping its existing `print` output verbatim (per-source progress lines, the summary, and the grouped `_show` output)
- [ ] 1.3 Run the existing test suite to confirm the refactor is behavior-preserving

## 2. Module scaffold

- [ ] 2.1 Create `rf_finder/ui/__init__.py` (empty package marker)
- [ ] 2.2 Create `rf_finder/ui/gui.py` with a `main()` entry point and a `if __name__ == "__main__": main()` guard so `python -m rf_finder.ui.gui` launches it
- [ ] 2.3 In `main()`, configure the shared cache exactly as the CLI does: `cache.configure(load_cache_config())`, then build and run the Tk root window

## 3. Ontology-driven form

- [ ] 3.1 Add a component-type `ttk.Combobox` populated from `COMPONENTS`, defaulting to `amplifier`
- [ ] 3.2 Implement `build_fields(component_type)` that calls `build_form(component_type)` and renders one input group per field, in order: min+max entries for range comparisons (`contains`/`between`/`min`/`max`), a single value entry for scalar `eq`
- [ ] 3.3 For every field render a unit `ttk.Combobox` of `field.units` with `units[0]` (canonical) selected by default
- [ ] 3.4 Store the widgets per field so their values can later be read out; rebuild (destroy + recreate) the field frame when the component-type selection changes, clearing prior values

## 4. Collect + search (background thread)

- [ ] 4.1 Implement `build_answers()` that reads the widgets into a dict using the `collect` key convention (`<name>.min`/`.max`/`.unit`, `<name>.value`/`.unit`), omitting empty entries
- [ ] 4.2 On Search: call `collect(schema, answers=build_answers())`; wrap in `try/except ValueError` and show the message via `messagebox.showerror`, leaving the form intact
- [ ] 4.3 Run the search on a `threading.Thread` by calling the shared `search_and_verify(provider, spec)` helper (same implementation the CLI uses)
- [ ] 4.4 Disable the Search button and show a loading indication while a search is running; block starting a second concurrent search
- [ ] 4.5 Hand results back to the UI thread with `root.after(0, ...)` before touching any widget

## 5. Results table

- [ ] 5.1 Add a `ttk.Treeview` with columns model, manufacturer, verdicts, url
- [ ] 5.2 Insert the already-sorted (match→partial→fail) rows, color-coding each by overall verdict via Treeview tags
- [ ] 5.3 Bind `<Double-1>` to open the row's url with `webbrowser.open`
- [ ] 5.4 When a search returns no candidates, show an explicit "no results" indication instead of an empty table
- [ ] 5.5 Clear previous results at the start of each new search

## 6. Verify

- [ ] 6.1 Add a headless unit test for `build_answers()` producing the expected key set (e.g. the `freq_range`/`P1dB` keystone), and a test that `search_and_verify` returns candidates ordered match→partial→fail, without driving Tk
- [ ] 6.2 Manually run `python -m rf_finder.ui.gui`: fill the amplifier form, run a search, confirm the table populates, colors match verdicts, double-click opens the datasheet, and a min>max entry shows an error dialog without crashing
- [ ] 6.3 Confirm `python -m rf_finder` (the existing CLI) still runs unchanged
