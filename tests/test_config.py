"""Tests for rf_finder/config.py — the max_results display cap loader."""

import pytest

from rf_finder.config import DEFAULT_MAX_RESULTS, ConfigError, load_max_results


def test_missing_file_uses_default(tmp_path):
    assert load_max_results(tmp_path / "nope.yaml") == DEFAULT_MAX_RESULTS


def test_missing_key_uses_default(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("something_else: 3\n", encoding="utf-8")
    assert load_max_results(path) == DEFAULT_MAX_RESULTS


def test_value_is_read(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("max_results: 25\n", encoding="utf-8")
    assert load_max_results(path) == 25


def test_zero_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("max_results: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_max_results(path)


def test_non_integer_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("max_results: lots\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_max_results(path)


def test_boolean_raises(tmp_path):
    # bool is a subclass of int; it must not sneak through as 1.
    path = tmp_path / "config.yaml"
    path.write_text("max_results: true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_max_results(path)
