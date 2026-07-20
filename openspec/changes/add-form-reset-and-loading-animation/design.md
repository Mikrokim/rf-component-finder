## Context

`rf_finder/ui/gui.py` is a single-file Tkinter + `ttkbootstrap` window. It runs the search off a background thread and communicates results back to the UI thread through a `queue.Queue` (`_result_queue`) that a periodic poller (`_poll_queue`, rescheduled every 100 ms) drains — this is the app's core threading discipline: **only the UI thread touches Tk**. Two engines share one results table: deterministic Search (`_on_search` → `_worker` → `search_and_verify`) and AI Search (`_on_run_skill` → `_skill_worker` → `run_demo_search`). Busy state is tracked by `_searching` / `_skill_running` and toggled by `_set_searching` / `_set_skill_running`, whose only visible feedback today is `status_var` text.

The AI runner (`rf_finder/agent/skill_runner.py`) already accepts an `on_text` callback and streams live progress to it (`on_text(text)` on each streamed chunk), but the GUI passes `on_text=lambda _t: None` and throws it away.

This change is GUI-only. It reuses every existing seam and adds no dependency.

## Goals / Non-Goals

**Goals:**
- One-click Reset that blanks the current form without changing component type.
- A themed, asset-free animated indicator shown while either engine runs.
- A real-time "thinking" line for AI Search, fed by the runner's existing `on_text` stream, delivered across threads the same way results already are.

**Non-Goals:**
- No change to `search_and_verify`, the adapters, or `skill_runner.py` (consumed as-is).
- No image/GIF asset and no new dependency (Pillow stays unused).
- No streamed line for deterministic Search — it produces no such stream.
- No change to the results table, verdict rendering, or component-type rebuild logic.

## Decisions

**1. Reset iterates `field_widgets`, does not rebuild.**
`build_fields()` already destroys and recreates widgets on type change; Reset must instead *keep* the widgets and clear them, so the form doesn't flicker or change type. It walks `self.field_widgets`, calling `.delete(0, "end")` on each `min`/`max`/`value` Entry and `.set(field.units[0])` on each unit Combobox. Rationale: reuses the existing widget records; no coupling to schema internals. *Alternative considered:* call `build_fields(self._selected_component_type())` — rejected because it rebuilds widgets unnecessarily and re-runs `build_form`, and is semantically "rebuild" not "clear".

**2. Reset participates in the existing busy-lock.**
The button is stored as `self.reset_button` and set to `disabled`/`normal` inside `_set_searching` and `_set_skill_running`, exactly like `search_button`/`skill_button`. Rationale: a single source of truth for "a run is in progress" already exists; Reset joins it rather than inventing a second guard.

**3. Animated indicator = a rotating-arc spinner drawn on a themed `tk.Canvas` (`_Spinner`).**
A small self-contained `_Spinner(tk.Canvas)` draws a faint full-circle track plus one bright arc segment, and advances the arc's start angle on an `after()` timer so it rotates — the familiar circular "loading" spinner. Colors come from the active `ttkbootstrap` palette (`Style().colors`: `primary` arc, `border` track, `bg` background). It lives in the controls row, is `pack`ed/`start()`ed when a run begins and `stop()`ed/`pack_forget`ed when it ends. Rationale: zero assets, themed automatically, and a true rotating circle — which the user explicitly preferred over a sliding bar. *Alternatives considered:* a `ttkbootstrap` indeterminate `Progressbar` (rejected — it is a sliding bar, not a rotating circle; the user asked for a spinner); a `ttkbootstrap` `Meter` gauge (rejected — a thick dial, heavier than a slim spinner); a Pillow-driven animated GIF (rejected — needs an asset file the project doesn't have).

**4. Streamed AI text reuses `_result_queue`, never touches Tk from the worker.**
`_skill_worker` currently passes a no-op `on_text`. It will instead pass `on_text=lambda t: self._result_queue.put(("skill_text", t))`. A new branch in `_poll_queue` handles `"skill_text"` by updating the activity line on the UI thread. Rationale: this is the *same* cross-thread channel results already use, so the single-threaded-Tk rule is preserved by construction. *Alternative considered:* a `root.after`-scheduled callback from the worker — rejected because scheduling from a non-UI thread is exactly the pattern the queue exists to avoid.

**5. Indicator + activity presentation.**
Keep `status_var` for terse summaries (counts, errors) and drive the live AI line through it as well (latest chunk, whitespace-collapsed and length-capped so it can't reflow the layout). The progressbar is the visual animation; the text line is the "keywords". On completion/error paths (`_deliver_results`, `_on_error`, `_deliver_skill_results`, `_on_skill_error`) the bar is stopped/hidden and the activity line cleared. Rationale: reuses the one status widget; both busy-setters own show/hide so every exit path already funnels through them.

## Risks / Trade-offs

- **Stream volume could spam the UI** → the poller drains the queue in a tight loop already; we only ever display the *latest* chunk (overwrite, not append) and cap its length, so bursty streaming can't degrade the UI or reflow widgets.
- **A stale progressbar left running if an exit path is missed** → every completion/error path already routes through `_set_searching(False)` / `_set_skill_running(False)`; putting `.stop()`+hide there (not at each call site) guarantees it stops exactly once per run.
- **`skill_text` arriving after `skill_done`/`skill_error`** → harmless: once busy is false the activity line is cleared; a late chunk would at worst flash text briefly. Acceptable for a cosmetic line; can be guarded by ignoring `skill_text` when `not self._skill_running` if it proves visible.
- **Test surface** → GUI is Tkinter; existing `tests/test_gui.py` drives it headlessly. New tests call the reset handler and feed a `skill_text` item through the queue/poller, asserting widget/state changes without a real window mainloop.

## Open Questions

- None blocking. Cosmetic polish (exact progressbar length, whether to also show an elapsed-time hint) can be decided during implementation without affecting the spec.
