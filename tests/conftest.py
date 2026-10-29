"""Fixtures communes."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Charger les intégrations de custom_components/."""
    yield
