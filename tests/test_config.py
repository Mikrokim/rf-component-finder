"""Tests for rf_finder/config.py — cache-scoped config loading."""

from pathlib import Path

import pytest

from rf_finder.config import (
    DEFAULT_MAX_RESULTS,
    CacheConfig,
    ConfigError,
    load_cache_config,
    load_max_results,
)


# ---------------------------------------------------------------------------
# Defaults (no file present)
# ---------------------------------------------------------------------------

class TestDefaults:
    """A missing config.yaml yields the committed defaults."""

    def test_missing_file_uses_defaults(self, tmp_path):
        cfg = load_cache_config(tmp_path / "does-not-exist.yaml")
        assert cfg == CacheConfig(
            cache_dir=Path(".cache/responses"), ttl_days=30, enabled=True
        )


# ---------------------------------------------------------------------------
# Values honored when present
# ---------------------------------------------------------------------------

class TestValuesHonored:
    """A well-formed config.yaml overrides the defaults."""

    def test_cache_section_is_read(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(
            "cache:\n"
            "  cache_dir: /tmp/pages\n"
            "  ttl_days: 3\n"
            "  enabled: false\n",
            encoding="utf-8",
        )
        cfg = load_cache_config(path)
        assert cfg == CacheConfig(cache_dir=Path("/tmp/pages"), ttl_days=3, enabled=False)

    def test_flat_top_level_keys_are_read(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("ttl_days: 10\nenabled: false\n", encoding="utf-8")
        cfg = load_cache_config(path)
        assert cfg.ttl_days == 10
        assert cfg.enabled is False
        assert cfg.cache_dir == Path(".cache/responses")   # unspecified → default

    def test_partial_config_fills_the_rest_from_defaults(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  ttl_days: 14\n", encoding="utf-8")
        cfg = load_cache_config(path)
        assert cfg.ttl_days == 14
        assert cfg.enabled is True


# ---------------------------------------------------------------------------
# Malformed / invalid files raise ConfigError
# ---------------------------------------------------------------------------

class TestMalformed:
    """A present-but-broken config surfaces a clear error, never silent defaults."""

    def test_invalid_yaml_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache: [unterminated\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)

    def test_non_mapping_document_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)

    def test_negative_ttl_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  ttl_days: -1\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)

    def test_non_integer_ttl_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  ttl_days: soon\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)

    def test_boolean_ttl_raises(self, tmp_path):
        # bool is a subclass of int; it must not sneak through as 1.
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  ttl_days: true\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)

    def test_non_boolean_enabled_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  enabled: 1\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_cache_config(path)


# ---------------------------------------------------------------------------
# Empty file is treated as no overrides
# ---------------------------------------------------------------------------

def test_empty_file_uses_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("", encoding="utf-8")
    cfg = load_cache_config(path)
    assert cfg == CacheConfig(
        cache_dir=Path(".cache/responses"), ttl_days=30, enabled=True
    )


# ---------------------------------------------------------------------------
# max_results (top-level display cap)
# ---------------------------------------------------------------------------

class TestMaxResults:
    """The ``max_results`` display cap, read from the top level of config.yaml."""

    def test_missing_file_uses_default(self, tmp_path):
        assert load_max_results(tmp_path / "nope.yaml") == DEFAULT_MAX_RESULTS

    def test_missing_key_uses_default(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("cache:\n  ttl_days: 3\n", encoding="utf-8")
        assert load_max_results(path) == DEFAULT_MAX_RESULTS

    def test_value_is_read(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("max_results: 25\n", encoding="utf-8")
        assert load_max_results(path) == 25

    def test_zero_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("max_results: 0\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_max_results(path)

    def test_non_integer_raises(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("max_results: lots\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_max_results(path)

    def test_boolean_raises(self, tmp_path):
        # bool is a subclass of int; it must not sneak through as 1.
        path = tmp_path / "config.yaml"
        path.write_text("max_results: true\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_max_results(path)
