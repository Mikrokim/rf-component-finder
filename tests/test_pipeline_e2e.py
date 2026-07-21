"""§8 — End-to-end tests for the management layer (``rf_finder.pipeline``).

The two gates and the datasheet chain are exercised through ``run_pipeline`` with
a fake adapter and a stubbed datasheet layer: real ``verify()``, no network, no
LLM. Each test maps to one §8 task in the change's tasks.md.
"""

from __future__ import annotations

import rf_finder.pipeline as pipeline
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue

# Table can answer freq + Gain; Temperature is the site-missing param (-> UNKNOWN).
_FREQ = ParamConstraint("freq_range", "contains", None, (10.0, 20.0), "GHz")
_GAIN = ParamConstraint("Gain", "min", 10.0, None, "dB")
_NF = ParamConstraint("NF", "max", 5.0, None, "dB")
_P1DB = ParamConstraint("P1dB", "min", 5.0, None, "dBm")
_TEMP = ParamConstraint("Temperature", "contains", None, (-20.0, 70.0), "degC")

_TABLE_OK = {"freq_range": RawValue((5.0, 40.0), "GHz"), "Gain": RawValue(20.0, "dB")}
_DS_TEMP_PASS = {"Temperature": RawValue((-40.0, 85.0), "degC")}


def _pcand(model="P1", raw=None, datasheet_url="http://ds/p1.pdf") -> Candidate:
    return Candidate(
        model=model, manufacturer="FakeCo", url=f"http://x/{model}",
        raw_params=dict(_TABLE_OK if raw is None else raw),
        source="table", datasheet_url=datasheet_url,
    )


class _Src:
    """A one-manufacturer source with configurable candidates and resolve behaviour."""

    manufacturer = "FakeCo"
    supported_components = {"amplifier"}

    def __init__(self, *cands, resolve="passthrough", raise_search=False):
        self._cands = list(cands)
        self._resolve = resolve
        self._raise = raise_search
        self.resolved: list[str] = []

    def search(self, spec):
        if self._raise:
            raise RuntimeError("source down")
        return self._cands

    def resolve_datasheet_url(self, cand):
        self.resolved.append(cand.model)
        if self._resolve == "passthrough":
            return cand.datasheet_url
        if self._resolve == "raise":
            raise RuntimeError("resolver blew up")
        return self._resolve(cand)


def _use(monkeypatch, *sources):
    monkeypatch.setattr(pipeline, "_sources_for", lambda spec: list(sources))


def _stub_datasheet(monkeypatch, *, raw=None, fetch_error=False, extract_error=False,
                    recorder=None):
    """Stub the datasheet chain that ``_enrich`` imports lazily."""
    import rf_finder.datasheet.extractor as ex_mod
    import rf_finder.datasheet.mapping as map_mod
    import rf_finder.datasheet.pdf as pdf_mod

    if fetch_error:
        def _fetch(url, **k):
            raise pdf_mod.DatasheetFetchError(url)
        monkeypatch.setattr(pdf_mod, "datasheet_text_from_url", _fetch)
        return
    monkeypatch.setattr(pdf_mod, "datasheet_text_from_url", lambda url, **k: "DSTEXT")

    def _extract(text, names):
        if recorder is not None:
            recorder.append(list(names))
        if extract_error:
            raise RuntimeError("llm unavailable")
        return {"names": list(names)}

    monkeypatch.setattr(ex_mod, "extract_rf_parameters", _extract)
    monkeypatch.setattr(map_mod, "to_raw_params", lambda params: dict(raw or {}))


def _spec(*constraints):
    return QuerySpec("amplifier", list(constraints))


def _outcomes(results):
    return {r.candidate.model: r.overall for r in results}


# --- 8.1 -------------------------------------------------------------------

def test_gate1_drops_a_table_fail_never_resolves_or_enriches(monkeypatch):
    bad = _pcand("BAD", raw={"freq_range": RawValue((5.0, 40.0), "GHz"),
                             "Gain": RawValue(2.0, "dB")})  # 2 < required 10 -> FAIL
    src = _Src(bad)
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN))

    assert out == []
    assert src.resolved == []  # dropped at Gate 1 -> never asked to resolve


# --- 8.2 -------------------------------------------------------------------

def test_survivor_enriched_from_datasheet_is_a_match(monkeypatch):
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert _outcomes(out) == {"P1": "match"}


# --- 8.3 -------------------------------------------------------------------

def test_datasheet_value_that_fails_is_dropped_by_gate2(monkeypatch):
    # Datasheet Temperature 0..40 does NOT cover the requested -20..70 -> FAIL.
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw={"Temperature": RawValue((0.0, 40.0), "degC")})

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert out == []  # a FAIL always drops


# --- 8.4 -------------------------------------------------------------------

def test_datasheet_read_but_silent_is_dropped_not_not_verified(monkeypatch):
    # Datasheet accessed successfully but yields nothing for Temperature.
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw={})  # read OK, no params found

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert out == []  # accessible + still UNKNOWN -> dropped, never not-verified


# --- 8.5 -------------------------------------------------------------------

def test_inaccessible_datasheet_below_coverage_is_dropped(monkeypatch):
    # freq+Gain+NF pass from the table (3), Temperature missing -> 3/4 = 0.75 < 0.80.
    cand = _pcand("P1", raw={"freq_range": RawValue((5.0, 40.0), "GHz"),
                             "Gain": RawValue(20.0, "dB"), "NF": RawValue(3.0, "dB")})
    src = _Src(cand)
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, fetch_error=True)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _NF, _TEMP))

    assert out == []


def test_inaccessible_datasheet_at_coverage_is_not_verified(monkeypatch):
    # freq+Gain+NF+P1dB pass from the table (4), Temperature missing -> 4/5 = 0.80.
    cand = _pcand("P1", raw={"freq_range": RawValue((5.0, 40.0), "GHz"),
                             "Gain": RawValue(20.0, "dB"), "NF": RawValue(3.0, "dB"),
                             "P1dB": RawValue(15.0, "dBm")})
    src = _Src(cand)
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, fetch_error=True)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _NF, _P1DB, _TEMP))

    assert _outcomes(out) == {"P1": "not-verified"}


# --- 8.6 -------------------------------------------------------------------

def test_only_site_missing_params_are_requested_from_the_extractor(monkeypatch):
    asked: list[list[str]] = []
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS, recorder=asked)

    pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert asked == [["Temperature"]]  # freq/Gain were table-answered, not re-asked


# --- 8.7 -------------------------------------------------------------------

def test_one_bad_source_does_not_abort_the_run(monkeypatch):
    good = _Src(_pcand("GOOD"))
    bad = _Src(raise_search=True)
    bad.manufacturer = "BadCo"
    _use(monkeypatch, bad, good)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert _outcomes(out) == {"GOOD": "match"}  # BadCo skipped, GOOD still returned


def test_a_raising_resolver_does_not_abort_the_run(monkeypatch):
    src = _Src(_pcand("P1"), resolve="raise")
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert isinstance(out, list)  # resolver raised, but the run completed


def test_a_failing_datasheet_does_not_abort_the_run(monkeypatch):
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, extract_error=True)  # extractor blows up

    out = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert isinstance(out, list)


# --- 8.8 -------------------------------------------------------------------

def test_result_exposes_only_the_public_fields(monkeypatch):
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    (res,) = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    assert res.candidate.model == "P1"
    assert res.candidate.manufacturer == "FakeCo"
    assert res.candidate.url == "http://x/P1"
    assert res.overall == "match"
    # the result contract itself carries no datasheet_url / source attribute
    assert not hasattr(res, "datasheet_url")
    assert not hasattr(res, "source")


# --- 8.9 -------------------------------------------------------------------

def test_enriched_candidate_surfaces_datasheet_params_in_verdicts(monkeypatch):
    src = _Src(_pcand("P1"))
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    (res,) = pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    verdicts = {v.canonical_name: v.status for v in res.verdicts}
    assert verdicts["Temperature"] == "PASS"  # the datasheet's parameter is verified
    assert "datasheet_url" not in vars(res)   # the link stays out of the result


# --- 8.10 ------------------------------------------------------------------

def test_resolution_only_for_survivors_with_a_missing_param(monkeypatch):
    # FULL answers every requested param from the table (Temperature included).
    full = _pcand("FULL", raw={**_TABLE_OK, "Temperature": RawValue((-40.0, 85.0), "degC")})
    missing = _pcand("MISS")  # Temperature not in the table -> missing
    dropped = _pcand("DROP", raw={"freq_range": RawValue((5.0, 40.0), "GHz"),
                                  "Gain": RawValue(1.0, "dB")})  # FAIL at Gate 1
    src = _Src(full, missing, dropped)
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    # FULL has nothing missing, DROP failed Gate 1 -> only MISS is resolved.
    assert src.resolved == ["MISS"]


# --- 8.11 ------------------------------------------------------------------

def test_pipeline_delegates_resolution_to_the_producing_adapter(monkeypatch):
    captured = {}

    def _resolve(cand):
        captured["model"] = cand.model
        return "http://ds/from-adapter.pdf"

    src = _Src(_pcand("OWN", datasheet_url=None), resolve=_resolve)
    _use(monkeypatch, src)
    _stub_datasheet(monkeypatch, raw=_DS_TEMP_PASS)

    pipeline.run_pipeline(_spec(_FREQ, _GAIN, _TEMP))

    # No per-site logic in the pipeline; it asks the adapter, for its own candidate.
    assert captured["model"] == "OWN"
    assert src.resolved == ["OWN"]
