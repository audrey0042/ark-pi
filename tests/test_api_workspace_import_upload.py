import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache, get_settings
from ark_pi.rag import index as rag_index
from ark_pi.web.app import create_app
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.export import export_workspace

SAMPLE_TEXT = "Ark Pi workspace import upload API test content."


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


def _export_bytes(client: TestClient) -> bytes:
    response = client.post("/api/workspace/export/download", json={})
    assert response.status_code == 200
    return response.content


def test_api_workspace_import_upload_imports_archive(
    client: TestClient,
    workspace_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)

    empty_workspace = tmp_path / "import-target"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    response = client.post(
        "/api/workspace/import/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["imported_count"] == 1
    assert data["imported_slugs"] == ["sample"]


def test_api_workspace_import_upload_lists_imported_index(
    client: TestClient,
    workspace_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)

    empty_workspace = tmp_path / "fresh-workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    upload = client.post(
        "/api/workspace/import/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert upload.status_code == 200

    indexes = client.get("/api/indexes").json()["indexes"]
    assert len(indexes) == 1
    assert indexes[0]["slug"] == "sample"


def test_api_workspace_import_upload_imported_index_is_searchable(
    client: TestClient,
    workspace_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)

    empty_workspace = tmp_path / "searchable-workspace"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    response = client.post(
        "/api/workspace/import/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 200

    entry = workspace_catalog.get_index(empty_workspace, "sample")
    assert entry is not None
    results = rag_index.search_index(Path(entry.index_dir), "import upload API", limit=3)
    assert len(results) >= 1


def test_api_workspace_import_upload_conflict_without_force_returns_400(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)

    response = client.post(
        "/api/workspace/import/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_api_workspace_import_upload_conflict_with_force_succeeds(
    client: TestClient,
    workspace_env: Path,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)

    response = client.post(
        "/api/workspace/import/upload?force=true",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1


def test_api_workspace_import_upload_empty_body_returns_400(
    client: TestClient,
    workspace_env: Path,
) -> None:
    response = client.post(
        "/api/workspace/import/upload",
        content=b"",
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_api_workspace_import_upload_invalid_zip_returns_400(
    client: TestClient,
    workspace_env: Path,
) -> None:
    response = client.post(
        "/api/workspace/import/upload",
        content=b"not a zip file",
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 400
    assert "not a valid zip" in response.json()["detail"]


def test_api_workspace_import_upload_traversal_archive_returns_400_and_writes_nothing(
    client: TestClient,
    workspace_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ingest_sample(client)
    data = _export_bytes(client)
    buffer = io.BytesIO(data)
    with zipfile.ZipFile(buffer, "a") as zf:
        zf.writestr("indexes/../escape.txt", "bad")
    bad_bytes = buffer.getvalue()

    empty_workspace = tmp_path / "empty-target"
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(empty_workspace))
    clear_settings_cache()

    response = client.post(
        "/api/workspace/import/upload",
        content=bad_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 400
    assert "unsafe path" in response.json()["detail"]
    assert workspace_catalog.list_indexes(empty_workspace) == []


def test_api_workspace_import_upload_oversized_returns_413(
    client: TestClient,
    workspace_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_sample(client)
    archive_bytes = _export_bytes(client)
    monkeypatch.setenv("ARK_MAX_IMPORT_BYTES", "100")
    clear_settings_cache()

    response = client.post(
        "/api/workspace/import/upload",
        content=archive_bytes,
        headers={"Content-Type": "application/zip"},
    )
    assert response.status_code == 413
    assert "exceeds maximum size" in response.json()["detail"]


def test_max_import_bytes_default() -> None:
    clear_settings_cache()
    settings = get_settings()
    assert settings.max_import_bytes == 52_428_800
