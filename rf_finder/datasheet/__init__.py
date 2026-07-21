"""Datasheet package — LLM-based parameter extraction from datasheet text.

The datasheet-fallback layer (future-requirements REQ-2.2): enrich parameters
that manufacturer listing pages don't publish (Size, MSL, Temperature, ...)
by extracting them from the part's datasheet, with ``source="datasheet"``.

Requires the ``llm`` optional dependency: ``pip install rf-finder[llm]``.
"""

from rf_finder.datasheet.code_extractors import (
    msl_level,
    size_dims,
    temp_range,
)
from rf_finder.datasheet.extractor import (
    EXTRACT_RF_PARAMETERS_INSTRUCTION,
    extract_rf_parameters,
)
from rf_finder.datasheet.mapping import to_raw_params
from rf_finder.datasheet.pdf import datasheet_text_from_pdf

__all__ = [
    "EXTRACT_RF_PARAMETERS_INSTRUCTION",
    "extract_rf_parameters",
    "to_raw_params",
    "datasheet_text_from_pdf",
    "temp_range",
    "size_dims",
    "msl_level",
]
