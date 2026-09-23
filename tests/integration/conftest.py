"""Wiring for the HTTP tests: a real app, with the two outbound
dependencies overridden so nothing reaches B2 or Anthropic."""

import pytest
from fastapi.testclient import TestClient

from blackblaze.api import app, get_describer, get_storage


@pytest.fixture
def client(storage, describer):
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_describer] = lambda: describer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
