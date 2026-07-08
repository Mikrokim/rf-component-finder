## Context

The search pipeline is already factored so an alternative front-end is cheap: `build_form(component_type)` yields the ontology-driven `FormSchema`, and `collect(schema, answers=...)` turns a plain `dict` of strings into a validated `QuerySpec` — the same seam the test suite uses. `run_search` in `rf_finder/__main__.py` shows the full flow (form → adapter `search` → `verify` → grouped output) and the required cache setup (`cache.configure(load_cache_config())`). The only thing that must change to add a GUI is the presentation layer; nothing in form/adapters/verifier/cache needs to move.

The constraint that shapes the design: adapter fetches take seconds (rate limits, large pages, background revalidation), and Tkinter is single-threaded — long work on the UI thread freezes the window. Tkinter widgets are also not thread-safe, so results computed off-thread must be handed back to the UI thread before touching widgets.

## Goals / Non-Goals

**Goals:**
- A Tkinter window (`rf_finder/ui/gui.py`, `python -m rf_finder.ui.gui`) that reproduces the CLI search as a form + results table, in English.
- Reuse `build_form` / `collect` / `adapter.search` / `verify` / `cache.configure` verbatim — zero duplicated parsing or ranking logic.
- Keep the window responsive during the multi-second fetch and never crash on bad input.

**Non-Goals:**
- No `refresh` command, no packaging to `.exe`/installer.
- No change to adapters, ontology, form, verifier, or cache behavior.
- No new third-party dependency; no persisted GUI settings or theming beyond basic color-coding.

## Decisions

### D1 — Tkinter/ttk, stdlib only
Tkinter ships with CPython, so the client needs no extra install, and `ttk.Combobox`/`ttk.Treeview` give an adequate native-looking dropdown and results grid. Chosen over Streamlit (needs `pip install` + a browser/server, less "an app") and PySide6/Qt (~100 MB dependency, overkill for one form). Trade-off: Tkinter styling is plain — acceptable for an internal client tool.

### D2 — Extract a shared headless search core; GUI is presentation-only
`run_search` today interleaves the logic (`build_form` → `collect` → adapter loop → `verify` → sort) with its terminal I/O (`input()`/`print()`), so there is no function a second front-end can call to just *get results*. We extract the terminal-free middle into:

```
def search_and_verify(provider, spec) -> list[VerifiedCandidate]:
    # select adapters whose supported_components include spec.component_type,
    # adapter.search(spec) per source (per-source exception isolation),
    # verify(spec, candidate) for each, sort match→partial→fail. No print/input.
```

`run_search` keeps its exact `print` wrapping but calls this helper for the work; the GUI imports and calls the **same** helper, then renders a table. This guarantees one physical search implementation shared by both front-ends — the GUI cannot drift from the CLI because it *is* the CLI's search. `gui.py` still owns only presentation: it calls `build_form`, `collect`, and `search_and_verify`, and computes no constraints or ranking itself. Alternative considered and rejected: a private copy of the loop inside `gui.py` (no CLI edit) — smaller blast radius, but two loops to keep in sync, which is exactly the drift the user asked to avoid.

Home for the helper: `rf_finder/__main__.py`, next to `run_search`, imported by the GUI as `from rf_finder.__main__ import search_and_verify` (mirrors the existing `from rf_finder.__main__ import _load_adapters` in `cli.py`). Importing `__main__` is side-effect-free (the `main()` call is under a `__name__ == "__main__"` guard).

### D3 — Background thread + thread-safe hand-off via `root.after`
The search runs in a `threading.Thread`; on completion it does **not** touch widgets directly. Instead it marshals the results back to the UI thread with `root.after(0, ...)`, the standard Tkinter pattern for "run this on the main loop". During the run the Search button is disabled and a loading label is shown, which both signals progress and enforces the "no concurrent search" requirement. Alternative considered: polling a `queue.Queue` from a periodic `after` tick — equivalent, but `after(0, callback)` is simpler for a single hand-off.

### D4 — Form widget model keyed by the answers convention
Each field builds its widgets from its `Field` (min/max entries for range comparisons, one value entry for scalar `eq`, a `ttk.Combobox` of `field.units` defaulting to `units[0]`). Widgets are stored in a small per-field record so that on Search we can emit exactly the `answers` keys `collect` expects (`<name>.min`/`.max`/`.unit` or `<name>.value`/`.unit`). Changing the component-type combobox destroys the current field frame and rebuilds from `build_form(new_type)`, so stale widgets can't leak values into the next spec.

### D5 — Results in a `ttk.Treeview`, color by verdict, double-click opens url
Results are sorted with the same `{match:0, partial:1, fail:2}` order as `run_search` and inserted into a `Treeview` with columns model/manufacturer/verdicts/url. Row background is set per overall verdict via Treeview tags (e.g. green/amber/neutral). A `<Double-1>` binding reads the row's url and calls `webbrowser.open`. Empty result set swaps the table for an explicit "no results" message.

### D6 — Errors surfaced, not fatal
`collect` is the one call that raises `ValueError` on bad input (unknown unit, min > max); the Search handler wraps it in `try/except ValueError` and shows `messagebox.showerror` with the message, leaving entries intact. Unexpected exceptions from adapters already isolate per-source in the loop (as in the CLI), so one failing site does not abort the search.

## Risks / Trade-offs

- **Tkinter not thread-safe** → all widget mutation happens on the UI thread only; the worker thread returns plain data and hands off via `root.after`.
- **Headless/CI or no display server** → `python -m rf_finder.ui.gui` can't open a window without a display. Acceptable: the GUI is for interactive client use; the CLI remains the automation path, and tests target the headless pieces (answers-dict building, result ordering) rather than driving Tk.
- **Logic drift between GUI and CLI** → eliminated by construction (D2): both call the one `search_and_verify` helper, so there is no second search loop to fall out of sync.
- **Refactor regresses the CLI** → `search_and_verify` is a pure cut-and-move of existing lines; `run_search`'s `print` output stays byte-for-byte the same. Verified by task 5.3 (run `python -m rf_finder` and confirm unchanged behavior) plus the existing test suite.
- **Plain Tkinter look** → acceptable for an internal tool; can be restyled later without spec impact.
