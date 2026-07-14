"""Model configuration for datasheet extraction.

``extractor.py`` is provider-agnostic — it asks GenAIFabric to run whichever
provider/model is named here, so switching models never touches the extraction
code. This module exposes the two names ``extractor.py`` imports
(``DATASHEET_PROVIDER`` / ``DATASHEET_MODEL``) from the single, git-ignored
config file ``rf-llm.env`` (which also holds the API key).

To switch models: edit ``rf-llm.env`` (``RF_LLM_PROVIDER`` / ``RF_LLM_MODEL``).
A real shell environment variable, if set, always overrides the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_env_file() -> None:
    """Load KEY=VALUE lines from the sibling ``rf-llm.env`` into ``os.environ``.

    Blank lines and ``#`` comments are ignored, surrounding quotes are stripped,
    and a variable already present in the real environment is never overridden.
    """
    env_path = Path(__file__).with_name("rf-llm.env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_env_file()

# provider: "gemini" | "openai" | "local" (Ollama) | "mock"
DATASHEET_PROVIDER = os.environ.get("RF_LLM_PROVIDER", "gemini")
# e.g. gemini-2.5-flash (cheap/fast) | gemini-2.5-pro (higher accuracy) | gemini-3.5-flash
DATASHEET_MODEL = os.environ.get("RF_LLM_MODEL", "gemini-2.5-flash")
