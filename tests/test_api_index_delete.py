from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ark_pi.config import clear_settings_cache
from ark_pi.web.app import create_app

SAMPLE_TEXT = (
    "Ark Pi splits work across two Raspberry Pis. "
    "The RAG Pi owns document ingestion, chunking, indexing, retrieval, and prompt assembly."
)


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


def _ingest_sample(client: TestClient, *, index_name: str = "sample") -> dict:
    response = client.post(
        "/api/ingest/text",
        json={
            "title": "Overview",
            "text": SAMPLE_TEXT,
            "index_name": index_name,
            "use_workspace": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_delete_index_removes_from_catalog(
    client: TestClient,
    workspace_env: Path,
) -> None:
    created = _ingest_sample(client)
    slug = created["index_slug"]
    index_dir = created["index_dir"]

    delete = client.delete(f"/api/indexes/{slug}")
    assert delete.status_code == 200
    data = delete.json()
    assert data["slug"] == slug
    assert data["deleted"] is True
    assert "Deleted workspace index" in data["message"]

    listed = client.get("/api/indexes")
    assert listed.status_code == 200
    slugs = [entry["slug"] for entry in listed.json()["indexes"]]
    assert slug not in slugs
    assert not Path(index_dir).exists()


def test_delete_missing_slug_returns_404(client: TestClient, workspace_env: Path) -> None:
    response = client.delete("/api/indexes/missing")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert data["detail"] == "Workspace index not found."


def test_delete_traversal_slug_returns_400_and_deletes_nothing(
    client: TestClient,
    workspace_env: Path,
) -> None:
    created = _ingest_sample(client)
    slug = created["index_slug"]

    response = client.delete("/api/indexes/../escape")
    assert response.status_code in {400, 404}

    listed = client.get("/api/indexes")
    assert listed.status_code == 200
    slugs = [entry["slug"] for entry in listed.json()["indexes"]]
    assert slug in slugs


def test_search_after_delete_fails_clearly(
    client: TestClient,
    workspace_env: Path,
) -> None:
    created = _ingest_sample(client)
    index_dir = created["index_dir"]
    slug = created["index_slug"]

    delete = client.delete(f"/api/indexes/{slug}")
    assert delete.status_code == 200

    search = client.post(
        "/api/search",
        json={"index_dir": index_dir, "query": "prompt assembly", "limit": 3},
    )
    assert search.status_code == 400


def test_delete_one_index_leaves_other_intact(
    client: TestClient,
    workspace_env: Path,
) -> None:
    first = _ingest_sample(client, index_name="alpha")
    second = _ingest_sample(client, index_name="beta")

    delete = client.delete(f"/api/indexes/{first['index_slug']}")
    assert delete.status_code == 200

    listed = client.get("/api/indexes")
    slugs = [entry["slug"] for entry in listed.json()["indexes"]]
    assert first["index_slug"] not in slugs
    assert second["index_slug"] in slugs
