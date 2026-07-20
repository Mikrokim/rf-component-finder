"""Tests for rf_finder/datasheet/extractor.py — LLM datasheet extraction.

Per the project constitution (principle V) the LLM path is tested against a
MockProvider — no network, no API key.  ``genaifabric`` is an optional extra
(``[llm]``) and may be absent from the test environment, so the mock lives
here: a minimal stand-in exposing the same ``runtime.run(...) -> result``
surface the extractor consumes, injected through the ``runtime`` parameter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from rf_finder.datasheet import (
    EXTRACT_RF_PARAMETERS_INSTRUCTION,
    extract_rf_parameters,
)
from rf_finder.datasheet.extractor import (
    _PARAM_ALIASES,
    _ground_categorical,
    _parse_size_spec,
)


# ---------------------------------------------------------------------------
# MockProvider / mock runtime
# ---------------------------------------------------------------------------

@dataclass
class _Result:
    """Mirror of GenAIFabric's run result: success flag, output text, error."""

    success: bool
    output: str = ""
    error: str | None = None


@dataclass
class MockProvider:
    """Canned-response provider: always answers with ``canned_output``."""

    canned_output: str = ""
    fail_with: str | None = None

    def respond(self) -> _Result:
        if self.fail_with is not None:
            return _Result(success=False, error=self.fail_with)
        return _Result(success=True, output=self.canned_output)


@dataclass
class MockRuntime:
    """GenAIFabric stand-in: routes ``run`` to a MockProvider, records calls."""

    provider_map: dict[str, MockProvider]
    calls: list[dict] = field(default_factory=list)

    def run(
        self, *, instruction: str, provider: str, input: dict, model=None,
        temperature=None,
    ) -> _Result:
        self.calls.append(
            {
                "instruction": instruction,
                "provider": provider,
                "input": input,
                "model": model,
                "temperature": temperature,
            }
        )
        return self.provider_map[provider].respond()


def _runtime(canned_output: str = "", fail_with: str | None = None) -> MockRuntime:
    provider = MockProvider(canned_output, fail_with)
    # Register under every provider name the tests exercise; the mock answers
    # the same regardless of which one the extractor routes to.
    return MockRuntime(
        provider_map={"openai": provider, "local": provider, "mock": provider}
    )


_FOUND_GAIN = {
    "unit": "dB", "min": 20.5, "typ": 22, "max": 23.5, "value": None,
    "condition": "@ 2 GHz",
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_found_and_not_found_parameters():
    rt = _runtime(json.dumps({"gain": _FOUND_GAIN, "noise_figure": None}))

    out = extract_rf_parameters("...", ["gain", "noise_figure"], runtime=rt)

    assert out == {"gain": _FOUND_GAIN, "noise_figure": None}


def test_run_receives_instruction_and_both_context_keys():
    rt = _runtime(json.dumps({"gain": None}))

    extract_rf_parameters("DATASHEET TEXT", ["gain"], runtime=rt)

    (call,) = rt.calls
    assert call["instruction"] == EXTRACT_RF_PARAMETERS_INSTRUCTION
    assert call["provider"] == "local"          # from DATASHEET_PROVIDER
    assert call["input"] == {
        "datasheet": "DATASHEET TEXT",
        "requested_parameters": ["gain"],
    }


def test_markdown_fences_are_stripped():
    fenced = "```json\n" + json.dumps({"gain": _FOUND_GAIN}) + "\n```"
    rt = _runtime(fenced)

    out = extract_rf_parameters("...", ["gain"], runtime=rt)

    assert out == {"gain": _FOUND_GAIN}


def test_thinking_model_preamble_is_stripped():
    # Local thinking models (e.g. qwen3) emit reasoning before the answer.
    thinky = (
        "<think>\nThe datasheet lists a gain of 22 dB typ.\n</think>\n"
        + json.dumps({"gain": _FOUND_GAIN})
    )
    rt = _runtime(thinky)

    out = extract_rf_parameters("...", ["gain"], runtime=rt)

    assert out == {"gain": _FOUND_GAIN}


def test_categorical_value_field_passes_through():
    # MSL / package / size are non-numeric — they arrive in "value" as a string.
    msl = {"unit": None, "min": None, "typ": None, "max": None,
           "value": "3", "condition": None}
    size = {"unit": "mm", "min": None, "typ": None, "max": None,
            "value": "9.00 x 8.00 mm", "condition": None}
    rt = _runtime(json.dumps({"msl": msl, "size": size}))

    out = extract_rf_parameters("...", ["msl", "size"], runtime=rt)

    assert out == {"msl": msl, "size": size}


def test_discrete_supply_list_value_passes_through():
    vdd = {"unit": "V", "min": None, "typ": None, "max": None,
           "value": [3, 5, 8], "condition": None}
    rt = _runtime(json.dumps({"vdd": vdd}))

    out = extract_rf_parameters("...", ["vdd"], runtime=rt)

    assert out["vdd"]["value"] == [3, 5, 8]


def test_model_comes_from_config_variable_not_a_parameter():
    # The model is read from DATASHEET_MODEL in rf_finder.config (qwen3:8b),
    # not passed as an argument.
    rt = _runtime(json.dumps({"gain": None}))

    extract_rf_parameters("...", ["gain"], runtime=rt)

    (call,) = rt.calls
    assert call["model"] == "qwen3:8b"


def test_extraction_pins_temperature_to_zero():
    # Extraction is a lookup, not a creative task: the same datasheet must
    # always yield the same values.  Providers default to sampling, which made
    # repeated runs disagree — so the extractor pins greedy decoding.
    rt = _runtime(json.dumps({"gain": None}))

    extract_rf_parameters("...", ["gain"], runtime=rt)

    (call,) = rt.calls
    assert call["temperature"] == 0


# ---------------------------------------------------------------------------
# Contract enforcement on the model's answer
# ---------------------------------------------------------------------------

def test_key_the_model_omitted_comes_back_as_none():
    rt = _runtime(json.dumps({"gain": _FOUND_GAIN}))  # impedance missing

    out = extract_rf_parameters("...", ["gain", "impedance"], runtime=rt)

    assert out == {"gain": _FOUND_GAIN, "impedance": None}


def test_extra_key_the_model_invented_is_dropped():
    rt = _runtime(json.dumps({"gain": _FOUND_GAIN, "hallucinated": 42}))

    out = extract_rf_parameters("...", ["gain"], runtime=rt)

    assert out == {"gain": _FOUND_GAIN}


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_provider_failure_raises_runtime_error():
    rt = _runtime(fail_with="quota exceeded")

    with pytest.raises(RuntimeError, match="quota exceeded"):
        extract_rf_parameters("...", ["gain"], runtime=rt)


def test_invalid_json_raises_value_error_with_raw_output():
    rt = _runtime("The gain is 22 dB.")  # prose, not JSON

    with pytest.raises(ValueError, match="invalid JSON"):
        extract_rf_parameters("...", ["gain"], runtime=rt)


# ---------------------------------------------------------------------------
# robust-param-extraction: pure helpers (no model)
# ---------------------------------------------------------------------------

_DIE_TEXT = "1.) Die size: 4530 µm x 6090 µm (+0/-50 µm)"


def test_parse_size_spec_from_value_string():
    length, width = _parse_size_spec({"value": "4530 µm x 6090 µm"}, _DIE_TEXT)
    assert length == {"unit": "µm", "typ": 4530}
    assert width == {"unit": "µm", "typ": 6090}


def test_parse_size_spec_from_min_max_pair():
    length, width = _parse_size_spec({"unit": "µm", "min": 4530, "max": 6090}, _DIE_TEXT)
    assert length["typ"] == 4530
    assert width["typ"] == 6090


def test_parse_size_spec_ungrounded_hallucination_is_nulled():
    # 9 x 8 is not a real dimension pair in the text -> nulled, not trusted.
    assert _parse_size_spec({"value": "9.00 x 8.00 mm"}, _DIE_TEXT) == (None, None)


def test_parse_size_spec_none_input_is_none():
    assert _parse_size_spec(None, _DIE_TEXT) == (None, None)


def test_ground_categorical_absent_is_nulled():
    assert _ground_categorical("MSL", {"value": "3"}, "no keyword here") is None


def test_ground_categorical_present_is_kept():
    # A categorical WITHOUT an override (package) is kept as-is when its
    # keyword is present. (MSL is re-derived from the text — see its own tests.)
    spec = {"value": "QFN"}
    assert _ground_categorical("package", spec, "Package outline: QFN") is spec


def test_msl_level_overrides_unreliable_model_value():
    # grf: model returns the trailing "--"; the text's "MSL 1" wins.
    out = _ground_categorical("MSL", {"value": "--"}, "Moisture Sensitivity Level MSL 1 --")
    assert out["value"] == "1"


def test_msl_level_avoids_260_trap():
    # adca: "(MSL) 3" is the level; the nearby "...Level 260°C" must not leak.
    out = _ground_categorical("MSL", {"value": "x"}, "(MSL) 3 info. Moisture Sensitivity Level 260°C")
    assert out["value"] == "3"


def test_msl_level_avoids_footnote_trap():
    # hmc: "msl3" is the level; the "msl rating [2]" footnote must not leak.
    out = _ground_categorical("MSL", {"value": "MSL3"}, "matte sn msl3. msl rating [2]")
    assert out["value"] == "3"


def test_msl_no_clean_level_falls_back_to_model():
    # Keyword present but no "MSL <n>" pattern -> keep the model's own answer
    # (which is null when the model likewise found nothing).
    spec = {"value": None}
    assert _ground_categorical("MSL", spec, "moisture sensitive device") is spec


def test_ground_categorical_non_categorical_passes_through():
    spec = {"typ": 20}
    assert _ground_categorical("Gain", spec, "anything") is spec


def test_vdd_aliases_include_drain_voltage():
    assert "Drain Voltage" in _PARAM_ALIASES["VDD"]


# ---------------------------------------------------------------------------
# robust-param-extraction: wiring through extract_rf_parameters (mocked model)
# ---------------------------------------------------------------------------

def test_length_width_split_from_model_size():
    # The model returns a "size"; the extractor splits it into length/width.
    rt = _runtime(json.dumps({"size": {"value": "4530 µm x 6090 µm"}}))
    out = extract_rf_parameters(
        "Die size: 4530 µm x 6090 µm", ["length", "width"], runtime=rt
    )
    assert out["length"]["typ"] == 4530
    assert out["width"]["typ"] == 6090
    assert set(out) == {"length", "width"}  # internal "size" is not returned


def test_length_width_null_when_size_ungrounded():
    # Model fabricates a size absent from the text -> length/width nulled.
    rt = _runtime(json.dumps({"size": {"value": "9.00 x 8.00 mm"}}))
    out = extract_rf_parameters(
        "Die size: 4530 µm x 6090 µm", ["length"], runtime=rt
    )
    assert out["length"] is None


def test_absent_categorical_is_grounded_to_null():
    rt = _runtime(json.dumps({"MSL": {"value": "3"}}))  # model fabricates a value
    out = extract_rf_parameters("datasheet with no keyword", ["MSL"], runtime=rt)
    assert out["MSL"] is None


def test_present_categorical_survives_grounding():
    rt = _runtime(json.dumps({"MSL": {"value": "1"}}))
    out = extract_rf_parameters(
        "Moisture Sensitivity Level MSL 1", ["MSL"], runtime=rt
    )
    assert out["MSL"]["value"] == "1"


def test_alias_hint_injected_when_supply_requested():
    rt = _runtime(json.dumps({"VDD": None}))
    extract_rf_parameters("Drain Voltage 28 V", ["VDD"], runtime=rt)
    (call,) = rt.calls
    assert "SYNONYMS" in call["instruction"]
    assert "Drain Voltage" in call["instruction"]


def test_no_alias_hint_when_no_supply_requested():
    rt = _runtime(json.dumps({"gain": None}))
    extract_rf_parameters("...", ["gain"], runtime=rt)
    (call,) = rt.calls
    assert "SYNONYMS" not in call["instruction"]
