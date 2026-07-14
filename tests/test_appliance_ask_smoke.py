import httpx
import pytest

from ark_pi.appliance_ask_smoke import (
    EXPECTED_PHRASE,
    SMOKE_INDEX_SLUG,
    SMOKE_SOURCE_FILENAME,
    run_appliance_ask_smoke,
)
from ark_pi.config import clear_settings_cache
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog


def _fake_llm_post(*_args: object, **_kwargs: object) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "The Ark Pi smoke-test beacon phrase is copper lantern.",
                    }
                }
            ]
        },
        request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
    )


@pytest.fixture
def rag_env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_ROLE", "dev")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    monkeypatch.setenv("ARK_LLM_BACKEND", "openai-compatible")
    monkeypatch.setenv("ARK_LLM_BASE_URL", "http://example.test")
    monkeypatch.setenv("ARK_INDEX_BACKEND", "simple")
    clear_settings_cache()
    yield workspace, source
    clear_settings_cache()


def test_run_appliance_ask_smoke_success(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source = rag_env
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = run_appliance_ask_smoke()

    assert result.ok is True
    assert result.retrieval_ok is True
    assert result.llm_ok is True
    assert EXPECTED_PHRASE in result.answer.lower()
    assert EXPECTED_PHRASE in result.retrieved_context_preview.lower()
    assert result.cleanup_performed is True
    assert not (source / SMOKE_SOURCE_FILENAME).exists()
    assert workspace_catalog.get_index(workspace, SMOKE_INDEX_SLUG) is None


def test_run_appliance_ask_smoke_keep_preserves_artifacts(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source = rag_env
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    result = run_appliance_ask_smoke(keep=True)

    assert result.ok is True
    assert result.cleanup_performed is False
    assert (source / SMOKE_SOURCE_FILENAME).is_file()
    assert workspace_catalog.get_index(workspace, SMOKE_INDEX_SLUG) is not None


def test_run_appliance_ask_smoke_llm_role_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "sources"
    workspace.mkdir()
    source.mkdir()
    monkeypatch.setenv("ARK_ROLE", "llm")
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source))
    clear_settings_cache()

    with pytest.raises(ValueError, match="Unsupported role 'llm'"):
        run_appliance_ask_smoke()


def test_run_appliance_ask_smoke_no_retrieval_hits(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_search(*_args: object, **_kwargs: object) -> rag_index.SearchExecutionResult:
        return rag_index.SearchExecutionResult(
            results=[],
            backend="simple",
            search_mode="lexical",
            query="",
        )

    monkeypatch.setattr("ark_pi.rag.index.search_index", empty_search)

    result = run_appliance_ask_smoke()

    assert result.ok is False
    assert result.retrieval_ok is False
    assert result.llm_ok is False
    assert result.retrieved_result_count == 0
    assert "no retrieval hits" in result.message


def test_run_appliance_ask_smoke_wrong_retrieval_skips_llm(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def wrong_search(*_args: object, **_kwargs: object) -> rag_index.SearchExecutionResult:
        return rag_index.SearchExecutionResult(
            results=[
                rag_index.SearchResult(
                    score=1.0,
                    id="x",
                    title="Wrong",
                    source="wrong.txt",
                    chunk_index=0,
                    text="nothing useful here",
                )
            ],
            backend="simple",
            search_mode="lexical",
            query="",
        )

    def fail_ask(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("run_ask should not be called when retrieval is wrong")

    monkeypatch.setattr("ark_pi.rag.index.search_index", wrong_search)
    monkeypatch.setattr("ark_pi.rag.ask.run_ask", fail_ask)

    result = run_appliance_ask_smoke()

    assert result.ok is False
    assert result.retrieval_ok is False
    assert result.llm_ok is False
    assert "retrieved context does not contain" in result.message


def test_run_appliance_ask_smoke_llm_connection_failure(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", fail_post)

    result = run_appliance_ask_smoke()

    assert result.ok is False
    assert result.retrieval_ok is True
    assert result.llm_ok is False
    assert "LLM error" in result.message


def test_run_appliance_ask_smoke_llm_timeout(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout_post(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", timeout_post)

    result = run_appliance_ask_smoke()

    assert result.ok is False
    assert result.retrieval_ok is True
    assert "LLM error" in result.message


def test_run_appliance_ask_smoke_wrong_llm_answer(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def wrong_post(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"choices": [{"message": {"content": "unknown phrase"}}]},
            request=httpx.Request("POST", "http://example.test/v1/chat/completions"),
        )

    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", wrong_post)

    result = run_appliance_ask_smoke()

    assert result.ok is False
    assert result.retrieval_ok is True
    assert result.llm_ok is False
    assert "generated answer does not contain" in result.message


def test_run_appliance_ask_smoke_idempotent(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    first = run_appliance_ask_smoke(keep=True)
    second = run_appliance_ask_smoke(keep=True)

    assert first.ok is True
    assert second.ok is True
    workspace, _source = rag_env
    entries = workspace_catalog.load_catalog(workspace)
    smoke_entries = [entry for entry in entries if entry.slug == SMOKE_INDEX_SLUG]
    assert len(smoke_entries) == 1


def test_run_appliance_ask_smoke_does_not_touch_user_index(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, source = rag_env
    user_source = source / "user-doc.txt"
    user_source.write_text("User-owned document content.\n", encoding="utf-8")
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    from ark_pi.workspace import ingest as workspace_ingest

    workspace_ingest.ingest_source_path_to_workspace_index(
        "user-doc.txt",
        "user-index",
        source,
        workspace,
        config_backend="simple",
        force=True,
    )

    result = run_appliance_ask_smoke()

    assert result.ok is True
    assert user_source.is_file()
    assert workspace_catalog.get_index(workspace, "user-index") is not None


def test_run_appliance_ask_smoke_cleanup_failure_reported(
    rag_env: tuple,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ark_pi.llm_client.openai_compat.httpx.post", _fake_llm_post)

    def fail_delete(*_args: object, **_kwargs: object) -> object:
        raise workspace_catalog.WorkspaceError("cleanup blocked")

    monkeypatch.setattr("ark_pi.workspace.catalog.delete_index", fail_delete)

    result = run_appliance_ask_smoke()

    assert result.ok is True
    assert result.cleanup_performed is False
    assert result.cleanup_error is not None
    assert "Cleanup failed" in result.message
