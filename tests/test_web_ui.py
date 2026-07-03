import pytest
from fastapi.testclient import TestClient

from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_get_root_returns_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_get_root_contains_expected_ui_elements(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Ark Pi" in html
    assert 'id="index-name"' in html
    assert 'id="index-select"' in html
    assert 'id="refresh-indexes"' in html
    assert "/api/indexes" in html
    assert 'id="question"' in html
    assert "/api/ask" in html
    assert "/api/ingest/text" in html
    assert "Add local file" in html
    assert "/api/ingest/path" in html
    assert 'id="path-ingest-form"' in html
    assert "Import text file" in html
    assert 'id="import-form"' in html
    assert 'id="import-file"' in html
    assert 'accept=".txt,text/plain"' in html
    assert 'id="delete-index"' in html
    assert "Delete selected index" in html
    assert "fetchDelete" in html
    assert "/api/indexes/" in html
    assert "window.confirm" in html
    assert "Export workspace" in html
    assert 'id="export-form"' in html
    assert "/api/workspace/export" in html
    assert "Download export" in html
    assert 'id="export-download-button"' in html
    assert "/api/workspace/export/download" in html
    assert "Export to path" in html
    assert "Import workspace" in html
    assert 'id="import-workspace-form"' in html
    assert "/api/workspace/import" in html
    assert "include_context" in html
    assert "include_prompt" in html


def test_get_ui_returns_same_html_as_root(client: TestClient) -> None:
    root = client.get("/")
    ui = client.get("/ui")
    assert root.status_code == 200
    assert ui.status_code == 200
    assert "text/html" in ui.headers.get("content-type", "")
    assert root.text == ui.text
