"""Tkinter desktop front-end for the RF component finder.

An alternative to the interactive terminal (`python -m rf_finder`): the same
search presented as a graphical form and a results table. It reuses the existing
flow unchanged — `build_form`/`collect` for input and the shared
`rf_finder.pipeline.run_pipeline` core for the work — so results are identical
to the CLI; only input and presentation differ.

Run with:  python -m rf_finder.ui.gui
"""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

import ttkbootstrap as ttk

from rf_finder.form import build_form, collect
from rf_finder.form.input import RANGE_COMPARISONS
from rf_finder.ontology.components import component_labels
from rf_finder.config import DEFAULT_MAX_RESULTS
from rf_finder.pipeline import run_pipeline

#: Per-parameter verdict symbols (matches the CLI's ``_STATUS`` glyphs).
_STATUS = {"PASS": "✓", "FAIL": "✗", "UNKNOWN": "?"}

#: Subtle row tints — green for a full match, amber for a not-verified result
#: (site parameters pass, but the datasheet could not confirm the rest).
_MATCH_ROW = "#e8f8ef"
_NOT_VERIFIED_ROW = "#fdf3e0"

#: ttkbootstrap theme for the whole window.
_THEME = "minty"

#: A number-in-progress: allows "", "-", "1", "1.", "-.5" — rejects letters as typed.
_NUM_RE = re.compile(r"^-?\d*\.?\d*$")


class App:
    """The main application window."""

    def __init__(self, root: tk.Tk, max_results: int = DEFAULT_MAX_RESULTS) -> None:
        self.root = root
        self.max_results = max_results

        root.title("RF Component Finder")
        root.minsize(820, 680)

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)

        # Header.
        ttk.Label(
            outer, text="RF Component Finder",
            font=("Segoe UI", 18, "bold"), bootstyle="primary",
        ).pack(anchor="w")
        ttk.Label(
            outer, text="Find components matching your spec across every manufacturer.",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(0, 12))

        # Filters group: component selector + ontology fields. No inner scroll —
        # every field is shown at once, comfortably spaced; the window is sized
        # to fit them all.
        self.form_area = ttk.Labelframe(outer, text="  Search filters  ", padding=14)
        self.form_area.pack(fill="x")

        self._build_component_selector()

        self.fields_frame = ttk.Frame(self.form_area)
        self.fields_frame.pack(fill="x", pady=(12, 0))

        # Numeric-only key validation, shared by every value entry.
        self._vcmd = (self.root.register(self._validate_numeric), "%P")

        # Per-field widget records, populated by build_fields() and read on search.
        self.field_widgets: list[dict] = []
        self.schema = None

        self.build_fields(self._selected_component_type())

        # Controls: the Search button and a status line (loading / result count).
        self._searching = False
        self.last_results: list = []
        controls = ttk.Frame(self.form_area)
        controls.pack(fill="x", pady=(16, 0))
        self.search_button = ttk.Button(
            controls, text="Search", command=self._on_search,
            bootstyle="success", width=16,
        )
        self.search_button.pack(side="left", ipady=4)
        self.status_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.status_var, bootstyle="secondary").pack(
            side="left", padx=(14, 0)
        )

        # Results group.
        self.results_area = ttk.Labelframe(outer, text="  Matching components  ", padding=8)
        self.results_area.pack(fill="both", expand=True, pady=(14, 0))

        # The worker thread hands results back through this queue; only the UI
        # thread ever touches Tk, by draining the queue on a periodic poll.
        self._result_queue: queue.Queue = queue.Queue()
        self.root.after(100, self._poll_queue)

        self._build_results()

    # -- Component-type selector --------------------------------------------

    def _build_component_selector(self) -> None:
        """A dropdown of component types; changing it rebuilds the form fields."""
        # Display the human label ("Amplifier") but keep the canonical key
        # ("amplifier") for build_form; _label_to_key maps back on selection.
        self._label_to_key = {label: key for key, label in component_labels().items()}
        labels = list(self._label_to_key)
        default_key = "amplifier" if "amplifier" in component_labels() else next(iter(component_labels()))
        default_label = component_labels()[default_key]

        row = ttk.Frame(self.form_area)
        row.pack(fill="x")
        ttk.Label(row, text="Component type:", font=("Segoe UI", 10, "bold")).pack(side="left")

        self.component_var = tk.StringVar(value=default_label)
        combo = ttk.Combobox(
            row, textvariable=self.component_var, values=labels,
            state="readonly", width=24,
        )
        combo.pack(side="left", padx=(8, 0))
        combo.bind("<<ComboboxSelected>>", self._on_component_change)

    def _selected_component_type(self) -> str:
        """The canonical component key currently chosen in the dropdown."""
        return self._label_to_key[self.component_var.get()]

    def _on_component_change(self, event=None) -> None:
        self.build_fields(self._selected_component_type())

    # -- Form fields ---------------------------------------------------------

    def build_fields(self, component_type: str) -> None:
        """Render one input group per field of ``build_form(component_type)``.

        Rebuilds from scratch each time (discarding any previously entered
        values), so switching component types never leaks stale input.
        """
        for child in self.fields_frame.winfo_children():
            child.destroy()
        self.field_widgets = []

        self.schema = build_form(component_type)
        for row, field in enumerate(self.schema.fields):
            self._build_field_row(row, field)

    def _build_field_row(self, row: int, field) -> None:
        """One grid row: label, min/max (range) or a single value (scalar), unit."""
        inner = self.fields_frame
        ttk.Label(inner, text=field.label, width=26, anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 10), pady=6
        )

        rec: dict = {"field": field}
        if field.comparison in RANGE_COMPARISONS:
            rec["kind"] = "range"
            rec["min"] = ttk.Entry(inner, width=12, validate="key", validatecommand=self._vcmd)
            rec["min"].grid(row=row, column=1, pady=6)
            ttk.Label(inner, text="to").grid(row=row, column=2, padx=6)
            rec["max"] = ttk.Entry(inner, width=12, validate="key", validatecommand=self._vcmd)
            rec["max"].grid(row=row, column=3, pady=6)
        else:
            rec["kind"] = "scalar"
            rec["value"] = ttk.Entry(inner, width=12, validate="key", validatecommand=self._vcmd)
            rec["value"].grid(row=row, column=1, pady=6)

        unit = ttk.Combobox(
            inner, values=list(field.units), state="readonly", width=8
        )
        unit.set(field.units[0])   # canonical unit first
        unit.grid(row=row, column=4, padx=(10, 0), pady=6)
        rec["unit"] = unit

        self.field_widgets.append(rec)

    # -- Collect + search ----------------------------------------------------

    def build_answers(self) -> dict[str, str]:
        """Read the form widgets into the ``answers`` dict ``collect`` expects.

        Range fields emit ``<name>.min`` / ``.max``; scalar fields emit
        ``<name>.value``. A ``<name>.unit`` is added only when that field has some
        input, so an untouched field contributes no keys and ``collect`` skips it.
        """
        answers: dict[str, str] = {}
        for rec in self.field_widgets:
            name = rec["field"].canonical_name
            unit = rec["unit"].get().strip()
            if rec["kind"] == "range":
                mn = rec["min"].get().strip()
                mx = rec["max"].get().strip()
                if mn:
                    answers[f"{name}.min"] = mn
                if mx:
                    answers[f"{name}.max"] = mx
                if (mn or mx) and unit:
                    answers[f"{name}.unit"] = unit
            else:
                val = rec["value"].get().strip()
                if val:
                    answers[f"{name}.value"] = val
                    if unit:
                        answers[f"{name}.unit"] = unit
        return answers

    @staticmethod
    def _validate_numeric(proposed: str) -> bool:
        """Entry key-validation: accept only a number-in-progress (see ``_NUM_RE``)."""
        return bool(_NUM_RE.match(proposed))

    def _validate_form(self) -> list[str]:
        """Field-level checks that ``collect`` can't express as an error.

        A ``contains`` field (e.g. freq_range) describes a band, so a one-sided
        entry is meaningless — and ``collect`` would silently *drop* it. Flag it
        instead of losing the user's intent. (``between``/``min``/``max`` fields
        legitimately allow an open side, so they are not checked here.)
        """
        errors: list[str] = []
        for rec in self.field_widgets:
            field = rec["field"]
            if rec["kind"] == "range" and field.comparison == "contains":
                has_min = bool(rec["min"].get().strip())
                has_max = bool(rec["max"].get().strip())
                if has_min != has_max:
                    errors.append(
                        f"{field.label}: enter both a minimum and a maximum "
                        f"(or leave both blank)."
                    )
        return errors

    def _on_search(self) -> None:
        """Validate + collect on the UI thread, then search on a worker thread."""
        if self._searching:
            return

        errors = self._validate_form()
        if errors:
            messagebox.showerror("Incomplete filters", "\n".join(errors))
            return

        try:
            spec = collect(self.schema, answers=self.build_answers())
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        self._set_searching(True)
        self._clear_results()
        threading.Thread(target=self._worker, args=(spec,), daemon=True).start()

    def _worker(self, spec) -> None:
        """Runs off the UI thread; hands results/errors back through the queue.

        It must never touch Tk directly (Tkinter is single-threaded): it only
        puts a message on ``_result_queue`` for ``_poll_queue`` to pick up on the
        UI thread.
        """
        try:
            verified = run_pipeline(spec)
        except Exception as e:   # never let a worker exception vanish silently
            self._result_queue.put(("error", e))
            return
        self._result_queue.put(("ok", verified))

    def _poll_queue(self) -> None:
        """Drain worker results on the UI thread; reschedule itself to keep polling."""
        try:
            while True:
                kind, payload = self._result_queue.get_nowait()
                if kind == "ok":
                    self._deliver_results(payload)
                else:
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _set_searching(self, busy: bool) -> None:
        """Toggle the loading state so a second search can't start mid-run."""
        self._searching = busy
        self.search_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.status_var.set("Searching… (this may take a few seconds)")

    def _on_error(self, exc: Exception) -> None:
        self._set_searching(False)
        self.status_var.set("")
        messagebox.showerror("Search failed", str(exc))

    def _deliver_results(self, verified: list) -> None:
        """Populate the table with accepted components (match + not-verified).

        The pipeline returns only accepted candidates, already ordered match
        first; each is tagged ``match`` or ``not-verified`` (its row tint).
        """
        self._set_searching(False)
        self.last_results = verified
        self._clear_results()

        if not verified:
            self.status_var.set("No matching components")
            self._show_empty("No matching components found — try relaxing the filters.")
            return

        n_match = sum(1 for v in verified if v.overall == "match")
        n_nv = sum(1 for v in verified if v.overall == "not-verified")

        shown = verified[:self.max_results]
        if len(verified) > self.max_results:
            self.status_var.set(
                f"Showing top {self.max_results} of {len(verified)} results "
                f"({n_match} match, {n_nv} not-verified) — refine the filters to narrow down"
            )
        else:
            self.status_var.set(f"{n_match} match(es), {n_nv} not-verified")

        self._show_tree()
        for v in shown:
            c = v.candidate
            verdicts = "  ".join(
                f"{vd.canonical_name}:{_STATUS.get(vd.status, '?')}" for vd in v.verdicts
            )
            item = self.tree.insert(
                "", "end",
                values=(c.model, c.manufacturer, verdicts, c.url),
                tags=(v.overall,),
            )
            self._row_urls[item] = c.url

    # -- Results table -------------------------------------------------------

    def _build_results(self) -> None:
        """A Treeview of results plus an empty-state label, in ``results_area``."""
        ttk.Style().configure("Treeview", rowheight=28)   # roomier rows

        cols = ("model", "manufacturer", "verdicts", "url")
        self.tree = ttk.Treeview(
            self.results_area, columns=cols, show="headings", bootstyle="success"
        )
        for key, text, width in (
            ("model", "Model", 180),
            ("manufacturer", "Manufacturer", 130),
            ("verdicts", "Verdicts", 260),
            ("url", "Product URL", 320),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")

        # Accepted rows get a subtle tint over the theme: green for a full
        # match, amber for a not-verified result.
        self.tree.tag_configure("match", background=_MATCH_ROW)
        self.tree.tag_configure("not-verified", background=_NOT_VERIFIED_ROW)

        self._vsb = ttk.Scrollbar(self.results_area, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self._vsb.set)
        self.tree.bind("<Double-1>", self._on_row_open)

        #: Treeview row id → datasheet url, for the double-click deep-link.
        self._row_urls: dict[str, str] = {}

        self.empty_label = ttk.Label(self.results_area, anchor="center")
        self._show_empty("No results yet — fill the form and click Search.")

    def _show_tree(self) -> None:
        self.empty_label.pack_forget()
        self.tree.pack(side="left", fill="both", expand=True)
        self._vsb.pack(side="right", fill="y")

    def _show_empty(self, message: str) -> None:
        self.tree.pack_forget()
        self._vsb.pack_forget()
        self.empty_label.configure(text=message)
        self.empty_label.pack(fill="both", expand=True)

    def _clear_results(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_urls.clear()

    def _on_row_open(self, event) -> None:
        """Double-click a row → open its datasheet url in the system browser."""
        item = self.tree.identify_row(event.y)
        url = self._row_urls.get(item)
        if url:
            webbrowser.open(url)


def main() -> None:
    """Build and run the window (adapters fetch live, like the CLI)."""
    from rf_finder.config import load_max_results

    root = ttk.Window(themename=_THEME)
    App(root, max_results=load_max_results())
    root.mainloop()


if __name__ == "__main__":
    main()
