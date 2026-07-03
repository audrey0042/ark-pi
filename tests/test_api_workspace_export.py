from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app

SAMPLE_TEXT = "Ark Pi workspace export API test content."


@pytest.fixture
def workspace_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(ws))
    clear_settings_cache()
    yield ws
    clear_settings_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _ingest_sample(client: TestClient) -> dict:
    response = client.post(
        "/api/ingest/text",
        json={
            "title": "Overview",
            "text": SAMPLE_TEXT,
            "index_name": "sample",
            "use_workspace": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_api_workspace_export_happy_path(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    output = tmp_path / "export.zip"

    response = client.post(
        "/api/workspace/export",
        json={"output_path": str(output)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["output_path"] == str(output.resolve())
    assert data["index_count"] == 1
    assert data["archive_size_bytes"] > 0
    assert output.is_file()
    with zipfile.ZipFile(output, "r") as archive:
        assert "catalog.json" in archive.namelist()


def test_api_workspace_export_existing_without_force_returns_400(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    output = tmp_path / "export.zip"
    output.write_text("existing", encoding="utf-8")

    response = client.post(
        "/api/workspace/export",
        json={"output_path": str(output)},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_api_workspace_export_missing_slug_returns_404(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    output = tmp_path / "export.zip"

    response = client.post(
        "/api/workspace/export",
        json={"output_path": str(output), "slug": "missing"},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
