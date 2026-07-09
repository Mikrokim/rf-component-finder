## Context

The search pipeline is already factored so an alternative front-end is cheap: `build_form(component_type)` yields the ontology-driven `FormSchema`, and `collect(schema, answers=...)` turns a plain `dict` of strings into a validated `QuerySpec` — the same seam the test suite uses. `main()` in `rf_finder/__main__.py` shows the full flow (form → adapter `search` → `verify` → grouped output). Adapters fetch live directly. The only thing that must change to add a GUI is the presentation layer.

The constraint that shapes the design: adapter fetches take seconds (rate limits, large pages), and Tkinter is single-threaded — long work on the UI thread freezes the window. Tkinter widgets are also not thread-safe, so results computed off-thread must be handed back to the UI thread before touching widgets.

## Goals / Non-Goals

**Goals:**
- A Tkinter window (`rf_finder/ui/gui.py`, `python -m rf_finder.ui.gui`) that reproduces the CLI search as a form + results table, in English.
- Reuse `build_form` / `collect` / `adapter.search` / `verify` verbatim — zero duplicated parsing or ranking logic; one search implementation shared with the CLI.
- Keep the window responsive during the multi-second fetch and never crash on bad input.

**Non-Goals:**
- No packaging to `.exe`/installer; no response-cache integration (adapters fetch live on this branch).
- No change to adapters, verifier, or form behavior.
- No 2D Size; no persisted GUI settings.

## Decisions

### D1 — Tkinter + ttkbootstrap
Tkinter ships with CPython; `ttkbootstrap` adds modern themes (chosen theme: `minty`) and keeps the `ttk.Treeview`/`Combobox` API, so the results grid and dropdowns look current with almost no extra code. Chosen over Streamlit (needs a browser/server, less "an app") and PySide6/Qt (~100 MB, and no native table story worth the weight). `ttkbootstrap` is the one added dependency.

### D2 — Extract a shared headless search core; GUI is presentation-only
`main()` today interleaves the logic (`build_form` → `collect` → adapter loop → `verify` → sort) with its terminal I/O (`input()`/`print()`), so there is no function a second front-end can call to just *get results*. We extract the terminal-free middle into:

```
def search_and_verify(spec, *, on_source=None) -> list[VerifiedCandidate]:
    # select adapters whose supported_components include spec.component_type,
    # adapter.search(spec) per source (per-source exception isolation),
    # verify(spec, candidate) for each, sort match→partial→fail. No print/input.
    # on_source(outcome, adapter, payload) is an optional progress hook so the CLI
    # can keep its per-source lines; the GUI passes None.
```

`main()` keeps its exact `print` wrapping but calls this helper for the work; the GUI imports and calls the **same** helper, then renders a table. This guarantees one physical search implementation shared by both front-ends — the GUI cannot drift from the CLI because it *is* the CLI's search. `gui.py` owns only presentation: it calls `build_form`, `collect`, and `search_and_verify`, and computes no constraints or ranking itself. Alternative considered and rejected: a private copy of the loop inside `gui.py` (no CLI edit) — smaller blast radius, but two loops to keep in sync, which is exactly the drift to avoid.

Home for the helper: a new terminal-free module `rf_finder/search.py` holding `_load_adapters`, `_sources_for`, and `search_and_verify`. Both front-ends import from it (`from rf_finder.search import search_and_verify`), keeping `__main__` as pure CLI glue. Chosen over parking it in `__main__.py` (would force the GUI to import the CLI entry point).

### D3 — Background thread + thread-safe hand-off via a `queue.Queue`
The search runs in a `threading.Thread`; on completion it does **not** touch widgets directly. The worker only `put`s a `("ok", results)` / `("error", exc)` message on a `queue.Queue`; a periodic `root.after(100, self._poll_queue)` tick — scheduled from and running on the UI thread — drains the queue and updates the widgets. During the run the Search button is disabled and a loading label is shown, which both signals progress and enforces the "no concurrent search" requirement. Alternative rejected: calling `root.after(0, ...)` from the worker thread — it crashed with `RuntimeError: main thread is not in main loop`, because registering the callback touches Tcl from the worker thread. The queue keeps every Tk call on the UI thread.

### D4 — Form widget model keyed by the answers convention
Each field builds its widgets from its `Field` (min/max entries for range comparisons, one value entry for scalar `eq`, a `ttk.Combobox` of `field.units` defaulting to `units[0]`). Widgets are stored in a per-field record so that on Search we emit exactly the `answers` keys `collect` expects (`<name>.min`/`.max`/`.unit` or `<name>.value`/`.unit`). Changing the component-type combobox rebuilds the field frame from `build_form(new_type)`, so stale widgets can't leak values. All fields are shown at once (no inner scroll); the window is sized to fit them.

### D5 — Matches-only results table, double-click opens url
Only `match` candidates are shown (partial/fail screened out, with a count), capped at `max_results` (default 10, from `config.yaml`). Rows go into a `Treeview` (columns model/manufacturer/verdicts/url), tinted for a match. A `<Double-1>` binding reads the row's url and calls `webbrowser.open`. No matches → an explicit "no matching components" message.

### D6 — Errors surfaced, not fatal
`collect` raises `ValueError` on bad input (e.g. min > max); the Search handler catches it and shows `messagebox.showerror`, leaving entries intact. Value entries also reject non-numeric keystrokes live, and a `contains` field with only one bound is flagged before searching (rather than `collect` silently dropping it). Per-source adapter exceptions isolate inside the core, so one failing site never aborts the search.

### D7 — Configurable result cap
`max_results` (default 10) is read from `config.yaml` by `load_max_results()` in `config.py`, and applied by both the GUI table and the CLI `match` group, so the two surfaces show the same count. It is a display setting, not tied to any cache config.

## Risks / Trade-offs

- **Tkinter not thread-safe** → all widget mutation happens on the UI thread only; the worker returns plain data via the queue (D3).
- **Headless/CI or no display server** → `python -m rf_finder.ui.gui` can't open a window without a display. The GUI tests skip when Tk can't initialize; the CLI remains the automation path.
- **Logic drift between GUI and CLI** → eliminated by construction (D2): both call the one `search_and_verify` helper.
- **Refactor regresses the CLI** → `search_and_verify` is a cut-and-move of existing lines; `main()`'s `print` output is preserved. Verified by running `python -m rf_finder` plus the test suite.
- **Live fetching is slow** → constraining a secondary param (Temperature/VDD/Size) can trigger heavy per-part fetches in some adapters; acceptable, and the cache integration (a separate effort) would address it later.
