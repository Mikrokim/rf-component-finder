"""Headless tests for the desktop GUI's non-Tk logic.

These exercise the pieces that turn form widgets into a search and validate input
— ``build_answers``, ``_validate_numeric``, ``_validate_form`` — without driving
the event loop. A real ``Tk`` root is still needed to construct the widgets, so
the whole module is skipped where no display is available (e.g. headless CI).
"""

from __future__ import annotations

import pytest

ttk = pytest.importorskip("ttkbootstrap")

import tkinter  # noqa: E402

import rf_finder.ui.gui as gui  # noqa: E402


@pytest.fixture
def app():
    """An ``App`` on a real (but never shown) root; skipped without a display."""
    try:
        root = ttk.Window(themename=gui._THEME)
    except tkinter.TclError:
        pytest.skip("no display available for Tk")
    root.withdraw()
    application = gui.App(root)
    yield application
    root.destroy()


def _field(app, canonical_name):
    for rec in app.field_widgets:
        if rec["field"].canonical_name == canonical_name:
            return rec
    raise KeyError(canonical_name)


# ---------------------------------------------------------------------------
# build_answers — the keystone from the structured-form-input spec
# ---------------------------------------------------------------------------


def test_build_answers_keystone(app):
    freq = _field(app, "freq_range")
    freq["min"].insert(0, "2")
    freq["max"].insert(0, "6")
    p1db = _field(app, "P1dB")
    p1db["min"].insert(0, "26")

    answers = app.build_answers()

    assert answers == {
        "freq_range.min": "2",
        "freq_range.max": "6",
        "freq_range.unit": "GHz",
        "P1dB.min": "26",
        "P1dB.unit": "dBm",
    }


def test_build_answers_empty_form_has_no_keys(app):
    assert app.build_answers() == {}


# ---------------------------------------------------------------------------
# Numeric key validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "12", "1.5", "-3", "-.5"])
def test_validate_numeric_accepts_numbers(text):
    assert gui.App._validate_numeric(text) is True


@pytest.mark.parametrize("text", ["abc", "1a", "2..3", "1,5"])
def test_validate_numeric_rejects_non_numbers(text):
    assert gui.App._validate_numeric(text) is False


# ---------------------------------------------------------------------------
# contains-both-bounds validation
# ---------------------------------------------------------------------------


def test_validate_form_flags_one_sided_contains(app):
    _field(app, "freq_range")["min"].insert(0, "2")   # min only, no max
    errors = app._validate_form()
    assert any("Frequency range" in e for e in errors)


def test_validate_form_allows_two_sided_contains(app):
    freq = _field(app, "freq_range")
    freq["min"].insert(0, "2")
    freq["max"].insert(0, "6")
    assert app._validate_form() == []


def test_validate_form_allows_one_sided_between(app):
    _field(app, "Gain")["min"].insert(0, "20")   # open-ended is legitimate here
    assert app._validate_form() == []


# ---------------------------------------------------------------------------
# Result cap (shared MAX_RESULTS)
# ---------------------------------------------------------------------------


def test_table_caps_matches_at_max_results(app):
    from rf_finder.models import Candidate, VerifiedCandidate

    cap = app.max_results

    def _match(i):
        c = Candidate(model=f"A{i}", manufacturer="X", url=f"u/{i}", raw_params={}, source="table")
        return VerifiedCandidate(candidate=c, verdicts=[], overall="match", confidence="table")

    app._deliver_results([_match(i) for i in range(cap + 5)])
    assert len(app.tree.get_children()) == cap
    assert str(cap + 5) in app.status_var.get()   # total surfaced in status


# ---------------------------------------------------------------------------
# AI Search — parameter formatting + rendering Skill results into the table
# ---------------------------------------------------------------------------


def test_format_spec_for_skill_keystone(app):
    from rf_finder.form import collect

    spec = collect(
        app.schema,
        answers={
            "freq_range.min": "14", "freq_range.max": "15", "freq_range.unit": "GHz",
            "P1dB.min": "24", "P1dB.unit": "dBm",
        },
    )
    text = app._format_spec_for_skill(spec)

    assert text.startswith("Component type: amplifier")
    assert "freq_range: 14.0 to 15.0 GHz" in text
    assert "P1dB: >= 24.0 dBm" in text
    assert " | " in text


def test_format_spec_for_skill_empty_form(app):
    from rf_finder.form import collect

    spec = collect(app.schema, answers={})
    text = app._format_spec_for_skill(spec)

    assert text.startswith("Component type: amplifier")
    assert "(no filters)" in text


def test_deliver_skill_results_maps_components_to_rows(app):
    components = [
        {"model": "M1", "manufacturer": "Mfr1", "url": "http://u1", "verdict": "match"},
        {"model": "M2", "manufacturer": "Mfr2", "url": "http://u2", "verdict": "partial"},
    ]
    app._deliver_skill_results((components, {"tokens": 1234, "num_turns": 5}))

    rows = app.tree.get_children()
    assert len(rows) == 2
    vals = app.tree.item(rows[0], "values")
    assert "AI" in vals[0]          # source marker (AI Search)
    assert vals[1] == "M1"          # model
    assert vals[2] == "Mfr1"        # manufacturer
    assert vals[3] == "match"       # verdict
    assert vals[4] == "http://u1"   # url
    assert app._row_urls[rows[0]] == "http://u1"   # double-click deep-link
    # Feature 2: completion + token/turn cost shown in the status line.
    assert "1,234 tokens" in app.status_var.get()


def _det_row(model="A"):
    from rf_finder.models import Candidate, VerifiedCandidate

    c = Candidate(model=model, manufacturer="X", url="u", raw_params={}, source="table")
    return VerifiedCandidate(candidate=c, verdicts=[], overall="match", confidence="table")


def test_empty_ai_search_keeps_existing_rows(app):
    """An AI Search that returns nothing must NOT clear the table."""
    app._deliver_results([_det_row()])
    assert len(app.tree.get_children()) == 1

    app._deliver_skill_results(([], {}))
    assert len(app.tree.get_children()) == 1          # existing row preserved
    assert "no components" in app.status_var.get()


def test_ai_search_appends_to_existing_results(app):
    """AI Search combines with existing rows; the Source column marks origin."""
    app._deliver_results([_det_row()])
    assert len(app.tree.get_children()) == 1

    # AI Search appends rather than replacing.
    app._deliver_skill_results(([{"model": "B", "manufacturer": "Y", "url": "v", "verdict": "match"}], {}))
    rows = app.tree.get_children()
    assert len(rows) == 2                              # combined: 1 Search + 1 AI
    sources = [app.tree.item(r, "values")[0] for r in rows]
    assert any("Search" in s for s in sources)
    assert any("AI" in s for s in sources)


def test_search_resets_table_including_ai_rows(app):
    """Only Search clears the table — it re-renders from scratch."""
    app._deliver_skill_results(([{"model": "B", "manufacturer": "Y", "url": "v", "verdict": "match"}], {}))
    assert len(app.tree.get_children()) == 1

    app._deliver_results([_det_row("A")])
    rows = app.tree.get_children()
    assert len(rows) == 1                              # Search reset the table
    assert "Search" in app.tree.item(rows[0], "values")[0]
