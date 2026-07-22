## 1. Reset button

- [x] 1.1 Add a `Reset` button to the `controls` frame in `App.__init__` (beside Search / AI Search), stored as `self.reset_button`, wired to a new `_on_reset` handler.
- [x] 1.2 Implement `_on_reset`: iterate `self.field_widgets`; for each record clear the `min`/`max`/`value` Entry widgets (`.delete(0, "end")`) and reset the `unit` Combobox to `field.units[0]` (`.set(...)`). Do not change the component type or rebuild fields. Return early if a run is in progress.
- [x] 1.3 In `_set_searching` and `_set_skill_running`, toggle `self.reset_button` state to `disabled`/`normal` alongside the existing buttons so Reset is blocked during any run.

## 2. Animated loading indicator

- [x] 2.1 Add a rotating-arc spinner widget (`_Spinner(tk.Canvas)`) — a faint track ring plus a bright arc rotated on an `after()` timer, themed from `ttkbootstrap` palette colors — in the controls row (kept hidden initially), stored as `self.spinner`.
- [x] 2.2 Add small helpers to show+`start()` and `stop()`+hide the spinner, callable only from the UI thread.
- [x] 2.3 Call "show+start" from `_set_searching(True)` and `_set_skill_running(True)`; call "stop+hide" from `_set_searching(False)` and `_set_skill_running(False)` so every completion/error path (which already routes through these) stops the animation exactly once.

## 3. Live AI Search activity stream

- [x] 3.1 In `_skill_worker`, replace `on_text=lambda _t: None` with `on_text=lambda t: self._result_queue.put(("skill_text", t))` so streamed chunks flow through the existing queue (worker never touches Tk).
- [x] 3.2 In `_poll_queue`, add a `"skill_text"` branch that renders the latest chunk on the UI thread (update `status_var`), collapsing whitespace and capping length so it can't reflow the layout.
- [x] 3.3 Clear the activity line on AI Search completion/error (in `_deliver_skill_results` / `_on_skill_error`, both of which call `_set_skill_running(False)`); ensure deterministic Search does not display a streamed line.

## 4. Tests

- [x] 4.1 In `tests/test_gui.py`, add a test that fills fields, invokes `_on_reset`, and asserts all value entries are empty and units are back to `field.units[0]`, with the component type unchanged.
- [x] 4.2 Add a test that asserts Reset (and the busy buttons) are disabled while `_searching`/`_skill_running` is true and re-enabled after.
- [x] 4.3 Add a test that feeds a `("skill_text", "...")` item through `_result_queue` + `_poll_queue` and asserts the activity line updates on the UI thread; and that a normal Search path shows no streamed line.

## 5. Verify

- [x] 5.1 Run `tests/test_gui.py` (and the GUI test suite) and confirm green. — 25 passed, 2 skipped; the 7 new tests all pass.
- [x] 5.2 Headless smoke confirmed: Reset clears the form and keeps the type; the progressbar shows during Search and AI Search and hides after; AI Search shows a live activity line that clears when done. (Interactive visual confirmation via `python -m rf_finder.ui.gui` is left to the user — a real window can't be driven in this headless environment.)
