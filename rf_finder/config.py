"""Loads config.yaml: manufacturer site list, rate limits, cache TTL (NFR-5).

# TODO(T9): implement config loader with validation and clear error on missing file.
"""

# LLM used to extract parameters from datasheet PDFs.
# Edit these to change the model/provider — no config file, no arguments.
DATASHEET_PROVIDER = "local"   # "local" (Ollama) | "openai" | "mock"
DATASHEET_MODEL = "qwen3:8b"   # model name for the chosen provider
