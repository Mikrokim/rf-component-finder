"""Loads user settings from an optional ``config.yaml`` in the working directory.

Currently only the result-display cap (``max_results``) is implemented; defaults
apply when the file (or the key) is absent, so the tool works with no config. A
file that exists but is malformed, or carries an out-of-range value, raises
``ConfigError`` rather than silently falling back to a default.
"""

from __future__ import annotations
import os
from pathlib import Path

# Load rf_finder/.env (sits next to this file) so RF_LLM_* and GEMINI_API_KEY
# are available via os.environ before the values below are read. Existing
# environment variables win over the file (dotenv default: override=False).
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

#: Default cap on how many matching results a front-end lists; override in config.yaml.
DEFAULT_MAX_RESULTS = 10

_CONFIG_FILENAME = "config.yaml"   # looked up relative to the working directory


class ConfigError(Exception):
    """Raised when ``config.yaml`` exists but is malformed or has invalid values."""


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

# # LLM used to extract parameters from datasheet PDFs.
# # Edit these to change the model/provider — no config file, no arguments.
DATASHEET_PROVIDER = "local"   # "local" (Ollama) | "openai" | "mock"
# DATASHEET_MODEL = "phi4-mini:latest" 
DATASHEET_MODEL = "llama3.1:8b"   # model name for the chosen provider
#provider: "gemini" | "openai" | "local" (Ollama) | "mock"
# DATASHEET_PROVIDER = os.environ.get("RF_LLM_PROVIDER", "gemini")
# # e.g. gemini-2.5-flash (cheap/fast) | gemini-2.5-pro (higher accuracy) | gemini-3.5-flash
# DATASHEET_MODEL = os.environ.get("RF_LLM_MODEL", "gemini-2.5-flash")
 