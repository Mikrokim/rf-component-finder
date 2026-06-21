"""pytest configuration for the adapters test sub-package.

Registers the ``network`` mark so pytest does not warn about unknown marks.
Tests decorated with ``@pytest.mark.network`` require live internet access and
are excluded from the default test run via ``-m "not network"``.
"""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "network: mark test as requiring live network access (deselect with -m 'not network')",
    )
