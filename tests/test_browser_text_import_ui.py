import pytest
from fastapi.testclient import TestClient

from ark_pi.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def html(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def test_import_text_file_panel_present(html: str) -> None:
    assert "Import text file" in html
    assert 'id="import-heading"' in html
    assert 'id="import-button"' in html


def test_import_file_input_accepts_txt(html: str) -> None:
    assert 'id="import-file"' in html
    assert 'accept=".txt,text/plain"' in html
    assert 'for="import-file"' in html


def test_import_uses_file_text_or_filereader(html: str) -> None:
    assert "readFileAsText" in html
    assert "file.text" in html or "FileReader" in html


def test_import_posts_to_ingest_text(html: str) -> None:
    assert 'id="import-form"' in html
    assert 'fetchJson("/api/ingest/text"' in html
    assert "use_workspace: true" in html


def test_add_text_panel_still_present(html: str) -> None:
    assert "Add text" in html
    assert 'id="ingest-form"' in html
    assert 'id="ingest-button"' in html


def test_add_local_file_panel_still_present(html: str) -> None:
    assert "Add local file" in html
    assert 'id="path-ingest-form"' in html
    assert "/api/ingest/path" in html


def test_ask_panel_still_present(html: str) -> None:
    assert "Ask" in html
    assert 'id="ask-form"' in html
    assert "/api/ask" in html
