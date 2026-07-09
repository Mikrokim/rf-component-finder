"""Loads settings from an optional ``config.yaml`` in the working directory.

Two independent slices are read here:
- **Cache settings** (``cache_dir``, ``ttl_days``, ``enabled``) — used by the HTTP
  service / storage layer (NFR-5). Only these cache keys of the planned T9 config
  are implemented; the full site list / rate limits remain future work.
- **The result-display cap** (``max_results``) — how many matches a front-end lists.

Defaults apply when ``config.yaml`` (or a key) is absent, so the tool works with no
configuration. A file that exists but is malformed, or carries an out-of-range
value, raises ``ConfigError`` rather than silently falling back to a default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (see design.md D7)
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_DIR = Path(".cache/responses")
_DEFAULT_TTL_DAYS = 30
_DEFAULT_ENABLED = True


#: Default cap on how many matching results a front-end lists; override in config.yaml.
DEFAULT_MAX_RESULTS = 10

_CONFIG_FILENAME = "config.yaml"   # looked up relative to the working directory


class ConfigError(Exception):
    """Raised when ``config.yaml`` exists but is malformed or has invalid values."""


@dataclass(frozen=True)
class CacheConfig:
    """Cache-scoped settings (a slice of the planned config.yaml)."""

    cache_dir: Path
    ttl_days: int
    enabled: bool


def load_cache_config(path: str | Path | None = None) -> CacheConfig:
    """Load the cache config from ``config.yaml``, falling back to defaults.

    ``path`` overrides the config-file location (mainly for tests); by default
    ``config.yaml`` is read from the current working directory. A missing file
    yields all defaults (``cache_dir=./.cache/responses``, ``ttl_days=30``,
    ``enabled=True``). Settings may sit at the top level or under a ``cache:``
    section. A file that exists but cannot be parsed, or that carries an
    out-of-range value, raises ``ConfigError``.
    """
    config_path = Path(path) if path is not None else Path(_CONFIG_FILENAME)

    data: dict = {}
    if config_path.is_file():
        import yaml  # lazy: only imported when a config file is actually present

        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"Malformed {config_path}: {exc}") from exc
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ConfigError(
                    f"{config_path} must be a mapping, got {type(loaded).__name__}"
                )
            # Accept either a nested `cache:` section or flat top-level keys.
            section = loaded.get("cache", loaded)
            if not isinstance(section, dict):
                raise ConfigError(f"{config_path} `cache` section must be a mapping")
            data = section

    cache_dir = Path(data.get("cache_dir", _DEFAULT_CACHE_DIR))
    ttl_days = data.get("ttl_days", _DEFAULT_TTL_DAYS)
    enabled = data.get("enabled", _DEFAULT_ENABLED)

    # ``bool`` is a subclass of ``int``; reject it explicitly so `ttl_days: true`
    # doesn't sneak through as 1, and `enabled: 1` isn't taken as a boolean.
    if isinstance(ttl_days, bool) or not isinstance(ttl_days, int) or ttl_days < 0:
        raise ConfigError(f"ttl_days must be a non-negative integer, got {ttl_days!r}")
    if not isinstance(enabled, bool):
        raise ConfigError(f"enabled must be a boolean, got {enabled!r}")

    return CacheConfig(cache_dir=cache_dir, ttl_days=ttl_days, enabled=enabled)
    
def load_max_results(path: str | Path | None = None) -> int:
    """Load the ``max_results`` display cap from ``config.yaml`` (top-level key).

    A missing file or key yields ``DEFAULT_MAX_RESULTS`` (10). A present value
    must be a positive integer, else ``ConfigError``.
    """
    config_path = Path(path) if path is not None else Path(_CONFIG_FILENAME)
    if not config_path.is_file():
        return DEFAULT_MAX_RESULTS

    import yaml  # lazy: only imported when a config file is actually present

    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed {config_path}: {exc}") from exc

    value = (loaded or {}).get("max_results", DEFAULT_MAX_RESULTS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"max_results must be a positive integer, got {value!r}")
    return value

# LLM used to extract parameters from datasheet PDFs.
# Edit these to change the model/provider — no config file, no arguments.
DATASHEET_PROVIDER = "local"   # "local" (Ollama) | "openai" | "mock"
DATASHEET_MODEL = "qwen3:8b"   # model name for the chosen provider
