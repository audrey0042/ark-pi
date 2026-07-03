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
    assert 'id="index-dir"' in html
    assert 'id="question"' in html
    assert "/api/ask" in html
    assert "include_context" in html
    assert "include_prompt" in html


def test_get_ui_returns_same_html_as_root(client: TestClient) -> None:
    root = client.get("/")
    ui = client.get("/ui")
    assert root.status_code == 200
    assert ui.status_code == 200
    assert "text/html" in ui.headers.get("content-type", "")
    assert root.text == ui.text
