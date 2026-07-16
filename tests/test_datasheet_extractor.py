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
