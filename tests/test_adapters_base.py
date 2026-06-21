"""Tests for rf_finder/adapters/base.py — T7 acceptance criteria."""

import pytest

from rf_finder.adapters.base import Adapter, AdapterError, ADAPTERS, register
from rf_finder.models import Candidate, QuerySpec


# ---------------------------------------------------------------------------
# Helpers — concrete subclasses used across tests
# ---------------------------------------------------------------------------

class _ConcreteAdapter(Adapter):
    manufacturer = "TestCo"
    supported_components = ["amplifier"]

    def search(self, spec: QuerySpec) -> list[Candidate]:
        return []


class _AnotherAdapter(Adapter):
    manufacturer = "OtherCo"
    supported_components = ["filter"]

    def search(self, spec: QuerySpec) -> list[Candidate]:
        return []


# ---------------------------------------------------------------------------
# AdapterError tests
# ---------------------------------------------------------------------------

def test_adapter_error_carries_attributes():
    cause = ValueError("underlying problem")
    err = AdapterError("Mini-Circuits", "HTTP 503", cause)
    assert err.manufacturer == "Mini-Circuits"
    assert err.context == "HTTP 503"
    assert err.cause is cause


def test_adapter_error_str_includes_manufacturer_and_context():
    err = AdapterError("Mini-Circuits", "timeout")
    s = str(err)
    assert "Mini-Circuits" in s
    assert "timeout" in s


def test_adapter_error_with_cause_none_does_not_crash():
    err = AdapterError("Acme", "not found", cause=None)
    assert err.cause is None
    # str() must not raise
    assert str(err)


def test_adapter_error_str_includes_cause_when_present():
    cause = RuntimeError("boom")
    err = AdapterError("Acme", "fetch failed", cause)
    assert "boom" in str(err)


# ---------------------------------------------------------------------------
# @register decorator tests
# ---------------------------------------------------------------------------

def test_register_adds_adapter_to_registry():
    # Use a fresh manufacturer name to avoid collisions with other tests
    @register
    class _Alpha(Adapter):
        manufacturer = "AlphaCo"
        supported_components = ["mixer"]

        def search(self, spec: QuerySpec) -> list[Candidate]:
            return []

    assert "AlphaCo" in ADAPTERS


def test_register_two_adapters_both_present():
    @register
    class _Beta(Adapter):
        manufacturer = "BetaCo"
        supported_components = ["attenuator"]

        def search(self, spec: QuerySpec) -> list[Candidate]:
            return []

    @register
    class _Gamma(Adapter):
        manufacturer = "GammaCo"
        supported_components = ["switch"]

        def search(self, spec: QuerySpec) -> list[Candidate]:
            return []

    assert "BetaCo" in ADAPTERS
    assert "GammaCo" in ADAPTERS


def test_registered_value_is_instance_not_class():
    @register
    class _Delta(Adapter):
        manufacturer = "DeltaCo"
        supported_components = ["amplifier"]

        def search(self, spec: QuerySpec) -> list[Candidate]:
            return []

    assert isinstance(ADAPTERS["DeltaCo"], _Delta)
    assert not isinstance(ADAPTERS["DeltaCo"], type)


# ---------------------------------------------------------------------------
# Adapter ABC instantiation tests
# ---------------------------------------------------------------------------

def test_abstract_adapter_without_search_raises_type_error():
    class _Incomplete(Adapter):
        manufacturer = "NoCo"
        supported_components = []
        # search() not implemented

    with pytest.raises(TypeError):
        _Incomplete()


def test_concrete_adapter_with_search_can_be_instantiated():
    adapter = _ConcreteAdapter()
    assert isinstance(adapter, Adapter)


def test_concrete_adapter_can_be_registered():
    # Manually register without the decorator to avoid side-effects on the
    # module-level ADAPTERS dict between test runs.
    key = _AnotherAdapter.manufacturer
    ADAPTERS[key] = _AnotherAdapter()
    assert key in ADAPTERS
    assert isinstance(ADAPTERS[key], _AnotherAdapter)
