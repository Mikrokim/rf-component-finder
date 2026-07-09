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


@pytest.fixture(autouse=True)
def _configure_cache(tmp_path):
    """Configure an isolated, empty response cache for every adapter test.

    Adapters now fetch through the shared HTTP service, which the CLI configures
    at startup; tests call ``search()`` directly, so they must configure it too.
    A fresh temp dir keeps tests isolated and — crucially for the ``network``
    tests — starts cold, so ``search()`` performs a real live fetch instead of
    serving a pre-existing cached page. Parse-only tests are unaffected (they
    call ``_parse_html`` / ``_parse_json`` and never touch the service).
    """
    from rf_finder import http
    from rf_finder.config import CacheConfig

    http.configure(
        CacheConfig(cache_dir=tmp_path / "cache", ttl_days=30, enabled=True)
    )
