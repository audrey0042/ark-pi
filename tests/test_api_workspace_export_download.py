import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app

SAMPLE_TEXT = "Ark Pi workspace export download API test content."


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


def test_api_workspace_export_download_returns_zip(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)

    response = client.post("/api/workspace/export/download", json={})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert 'filename="ark-pi-workspace-export.zip"' in response.headers["content-disposition"]
    assert len(response.content) > 0


def test_api_workspace_export_download_zip_contains_manifest_and_catalog(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)

    response = client.post("/api/workspace/export/download", json={})
    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content), "r") as archive:
        names = set(archive.namelist())
        assert "catalog.json" in names
        assert "export_manifest.json" in names
        catalog = json.loads(archive.read("catalog.json"))
        assert catalog["indexes"][0]["slug"] == "sample"
        manifest = json.loads(archive.read("export_manifest.json"))
        assert manifest["created_by"] == "ark-pi"


def test_api_workspace_export_download_single_slug(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)
    client.post(
        "/api/ingest/text",
        json={
            "title": "Other",
            "text": "Other index content for export download test.",
            "index_name": "other",
            "use_workspace": True,
        },
    )

    response = client.post(
        "/api/workspace/export/download",
        json={"slug": "sample"},
    )
    assert response.status_code == 200
    assert 'filename="ark-pi-index-sample.zip"' in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content), "r") as archive:
        catalog = json.loads(archive.read("catalog.json"))
        assert len(catalog["indexes"]) == 1
        assert catalog["indexes"][0]["slug"] == "sample"
        assert not any(name.startswith("indexes/other/") for name in archive.namelist())


def test_api_workspace_export_download_missing_slug_returns_404(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)

    response = client.post(
        "/api/workspace/export/download",
        json={"slug": "missing"},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_api_workspace_export_download_empty_catalog_returns_400(
    client: TestClient,
    workspace_env: Path,
) -> None:
    response = client.post("/api/workspace/export/download", json={})
    assert response.status_code == 400
    assert "catalog is empty" in response.json()["detail"]


def test_api_workspace_export_download_does_not_require_output_path(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)

    response = client.post("/api/workspace/export/download", json={})
    assert response.status_code == 200
    assert "output_path" not in response.headers
