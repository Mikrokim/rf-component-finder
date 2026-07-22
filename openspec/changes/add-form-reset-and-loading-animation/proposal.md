## Why

The desktop GUI works but feels static: there is no way to clear a filled form except deleting each field by hand or switching component type (which also loses the type), and while a search runs the only feedback is a frozen text line — the window gives no living sign that it is working, and the AI Search hides the rich progress it already produces. Two small, low-risk touches make the form faster to reuse and make waiting feel alive.

## What Changes

- Add a **Reset** button to the controls row (beside Search / AI Search) that clears every form field in one click — each value entry emptied and each unit restored to its canonical default — without changing the selected component type. It is disabled while a search or AI search is running, like the other buttons.
- Replace the static "Searching…" text with an **animated loading indicator** (a built-in `ttkbootstrap` animated widget — no image/GIF asset) shown while a search runs and hidden when results or an error arrive.
- For **AI Search**, additionally surface a **live "thinking" activity line**: the AI engine already streams progress through `run_demo_search`'s `on_text` callback, but the GUI discards it. Pipe that stream (via the existing `_result_queue`, rendered on the UI thread) so the latest activity/keywords appear in real time as the AI works.

All changes are confined to the GUI layer. The search pipeline (`search_and_verify`), the adapters, and the AI skill runner are unchanged; the loading stream reuses the callback the runner already exposes.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `desktop-gui`: Adds a one-click form-reset requirement, and strengthens the in-progress feedback from a generic "loading indication" to an animated indicator plus, for AI Search, a live streamed activity line. (The `desktop-gui` capability currently lives in the unarchived `add-desktop-gui` change; this delta layers new requirements on top of it.)

## Impact

- **Code**: `rf_finder/ui/gui.py` only — the controls row, the search/AI-search busy toggles (`_set_searching`, `_set_skill_running`), the queue poller (`_poll_queue`), and the AI worker's `on_text` wiring (`_skill_worker`).
- **Tests**: `tests/test_gui.py` — add coverage for reset and for the streamed-status path.
- **Dependencies**: none added — `ttkbootstrap` (already used) provides the animated widget; `Pillow` is already installed but not needed for the chosen asset-free approach.
- **Out of scope**: `search_and_verify`, adapters, `rf_finder/agent/skill_runner.py` (consumed as-is), and the CLI are untouched.
