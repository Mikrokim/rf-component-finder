"""Terminal-free search core shared by the CLI and the desktop GUI.

``run_search`` (the interactive CLI in ``rf_finder.__main__``) and the Tkinter GUI
both drive the same flow: pick the adapters that support the requested component,
fetch candidates from each, verify every candidate against the query, and rank the
results. That flow lives here, with no ``input``/``print`` of its own, so both
front-ends call one implementation and cannot drift apart. Presentation (prompts,
tables, progress lines) stays in each front-end.
"""

from __future__ import annotations


def _load_adapters():
    """Import every adapter module (triggers @register) and return the registry."""
    from rf_finder.adapters.minicircuits import MiniCircuitsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.amcomusa import AmcomUSAAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.analogdevices import AnalogDevicesAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.marki import MarkiMicrowaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.rwmmic import RwmmicAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.macom import MacomAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.ums import UmsAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.threerwave import ThreeRWaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.microchip import MicrochipAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.guerrillarf import GuerrillaRFAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.vectrawave import VectraWaveAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.qorvo import QorvoAdapter  # noqa: F401 (triggers @register)
    from rf_finder.adapters.base import ADAPTERS

    return ADAPTERS


def _sources_for(spec):
    """Adapters that support ``spec.component_type`` (in registry/search order)."""
    adapters = _load_adapters()
    return [a for a in adapters.values() if spec.component_type in a.supported_components]


def search_and_verify(spec, *, on_source=None):
    """Run every supporting adapter, verify each candidate, rank match→partial→fail.

    The terminal-free core of the search. It performs no ``input``/``print``;
    progress is reported only through the optional ``on_source(outcome, adapter,
    payload)`` hook, called once per source with ``outcome`` in
    ``{"error", "empty", "ok"}`` — ``payload`` is the raised exception for
    ``"error"``, ``None`` for ``"empty"``, and the candidate list for ``"ok"``.
    One failing source never aborts the rest.

    Returns the ``VerifiedCandidate`` list sorted match first, then partial, then
    fail (a stable sort, so discovery order is preserved within each group).
    """
    from rf_finder.verifier import verify

    candidates = []
    for adapter in _sources_for(spec):
        try:
            found = adapter.search(spec)
        except Exception as e:  # one bad source must not stop the others
            if on_source is not None:
                on_source("error", adapter, e)
            continue
        if not found:
            if on_source is not None:
                on_source("empty", adapter, None)
            continue
        candidates.extend(found)
        if on_source is not None:
            on_source("ok", adapter, found)

    verified = [verify(spec, c) for c in candidates]
    order = {"match": 0, "partial": 1, "fail": 2}
    verified.sort(key=lambda v: order.get(v.overall, 9))
    return verified
