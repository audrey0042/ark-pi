from pathlib import Path
import zipfile

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app

SAMPLE_TEXT = "Ark Pi workspace import API test content."


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


def _export_archive(client: TestClient, output: Path) -> None:
    response = client.post(
        "/api/workspace/export",
        json={"output_path": str(output)},
    )
    assert response.status_code == 200


def test_api_workspace_import_happy_path(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample(client)
    archive = tmp_path / "export.zip"
    _export_archive(client, archive)

    empty_workspace = tmp_path / "import-target"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    response = client.post(
        "/api/workspace/import",
        json={"archive_path": str(archive)},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["imported_count"] == 1
    assert data["imported_slugs"] == ["sample"]
    assert data["archive_path"] == str(archive.resolve())

    list_response = client.get("/api/indexes")
    assert list_response.status_code == 200
    slugs = [item["slug"] for item in list_response.json()["indexes"]]
    assert "sample" in slugs


def test_api_workspace_import_conflict_without_force_returns_400(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    archive = tmp_path / "export.zip"
    _export_archive(client, archive)

    response = client.post(
        "/api/workspace/import",
        json={"archive_path": str(archive)},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_api_workspace_import_invalid_archive_returns_400(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_text("not a zip", encoding="utf-8")

    response = client.post(
        "/api/workspace/import",
        json={"archive_path": str(bad)},
    )
    assert response.status_code == 400
    assert "not a valid zip" in response.json()["detail"]


def test_api_workspace_import_lists_imported_index_after_import(
    client: TestClient,
    workspace_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample(client)
    archive = tmp_path / "export.zip"
    _export_archive(client, archive)

    empty_workspace = tmp_path / "fresh-workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    import_response = client.post(
        "/api/workspace/import",
        json={"archive_path": str(archive)},
    )
    assert import_response.status_code == 200

    indexes = client.get("/api/indexes").json()["indexes"]
    assert len(indexes) == 1
    assert indexes[0]["slug"] == "sample"
    with zipfile.ZipFile(archive, "r") as zf:
        assert "catalog.json" in zf.namelist()
