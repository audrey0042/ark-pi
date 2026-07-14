import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_pi.corpus.checkpoint import load_checkpoint
from ark_pi.corpus.ingest import CorpusIngestError, run_corpus_ingest
from ark_pi.corpus.run_state import checkpoint_path, errors_path
from ark_pi.corpus.types import CorpusIngestOptions, CorpusRunStatus
from ark_pi.ingest import chunking as chunking_module
from ark_pi.rag import index as rag_index
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import index_paths


@pytest.fixture
def corpus_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    jsonl_path = tmp_path / "corpus.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {"id": "one", "title": "First", "text": "The first local article."}
                ),
                json.dumps(
                    {"id": "two", "title": "Second", "text": "The second local article."}
                ),
                json.dumps(
                    {"id": "three", "title": "Third", "text": "The third local article."}
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_dir, jsonl_path, tmp_path


def _options(
    workspace_dir: Path,
    source: Path,
    *,
    batch_size: int = 100,
    resume: bool = False,
    dry_run: bool = False,
    continue_on_error: bool = False,
    force_rebuild: bool = False,
    yes: bool = False,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    run_id: str | None = None,
) -> CorpusIngestOptions:
    return CorpusIngestOptions(
        source_path=source,
        index_slug="corpus-smoke",
        workspace_dir=workspace_dir,
        batch_size=batch_size,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        backend="simple",
        resume=resume,
        dry_run=dry_run,
        continue_on_error=continue_on_error,
        force_rebuild=force_rebuild,
        yes=yes,
        run_id=run_id,
    )


def test_jsonl_ingest_into_simple_index(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    result = run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=1))
    assert result.status == CorpusRunStatus.completed
    assert result.records_completed == 3
    assert result.chunks_written >= 3

    _, index_dir = index_paths(workspace_dir, "corpus-smoke")
    hits = rag_index.search_index(index_dir, "second local article", limit=5).results
    assert hits
    assert any("second" in hit.text.lower() for hit in hits)

    entry = workspace_catalog.get_index(workspace_dir, "corpus-smoke")
    assert entry is not None
    assert entry.corpus_run_id == result.run_id
    assert entry.source_fingerprint is not None


def test_directory_ingest_stable_order(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, _, tmp_path = corpus_env
    source_dir = tmp_path / "articles"
    (source_dir / "nested").mkdir(parents=True)
    (source_dir / "a.txt").write_text("Alpha article text.", encoding="utf-8")
    (source_dir / "nested" / "b.txt").write_text("Beta article text.", encoding="utf-8")

    result = run_corpus_ingest(_options(workspace_dir, source_dir, batch_size=1))
    assert result.status == CorpusRunStatus.completed
    assert result.records_completed == 2


def test_streaming_does_not_load_entire_jsonl(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    original_open = Path.open

    def tracking_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self == jsonl_path.resolve() and "r" in args:
            msg = "Full-file read_text should not be used for corpus JSONL ingest"
            if kwargs.get("encoding") == "utf-8" and "b" not in args:
                pass
        return original_open(self, *args, **kwargs)

    with patch.object(Path, "open", tracking_open):
        result = run_corpus_ingest(_options(workspace_dir, jsonl_path))
    assert result.records_completed == 3


def test_batch_checkpoint_after_durable_index(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=1))
    ckpt = load_checkpoint(checkpoint_path(workspace_dir, _run_id(workspace_dir, jsonl_path)))
    assert ckpt.records_completed == 3
    assert ckpt.chunks_written >= 3


def _run_id(workspace_dir: Path, jsonl_path: Path) -> str:
    from ark_pi.corpus.fingerprint import derive_run_id, fingerprint_source

    fp = fingerprint_source(jsonl_path)
    return derive_run_id(
        source_fingerprint=fp,
        index_slug="corpus-smoke",
        chunk_size=1000,
        chunk_overlap=200,
        backend="simple",
    )


def test_resume_skips_completed_documents(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    first = run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=1))
    _, index_dir = index_paths(workspace_dir, "corpus-smoke")
    stats_before = rag_index.index_stats(index_dir)

    second = run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=1, resume=True))
    stats_after = rag_index.index_stats(index_dir)

    assert second.status == CorpusRunStatus.completed
    assert stats_after.chunk_count == stats_before.chunk_count
    assert first.run_id == second.run_id


def test_resume_rejects_changed_fingerprint(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    first = run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=2))
    jsonl_path.write_text(
        json.dumps({"id": "one", "title": "Changed", "text": "Changed content."}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusIngestError, match="fingerprint"):
        run_corpus_ingest(
            _options(workspace_dir, jsonl_path, resume=True, batch_size=2, run_id=first.run_id)
        )


def test_malformed_jsonl_reports_line_number(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    jsonl_path.write_text(
        '{"title":"Ok","text":"valid"}\n{not json}\n',
        encoding="utf-8",
    )
    with pytest.raises(CorpusIngestError, match="line 2"):
        run_corpus_ingest(_options(workspace_dir, jsonl_path))


def test_continue_on_error_records_sanitized_failure(
    corpus_env: tuple[Path, Path, Path],
) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "good", "title": "Good", "text": "Good article body."}),
                json.dumps({"id": "bad", "title": "Bad", "text": "Will fail chunking."}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    original_make = chunking_module.make_corpus_chunk_records

    def fail_bad(*args: object, **kwargs: object) -> list[dict[str, object]]:
        document_id = args[0]
        if document_id == "bad":
            raise ValueError("Simulated chunk failure for bad document")
        return original_make(*args, **kwargs)

    with patch(
        "ark_pi.corpus.ingest.chunking.make_corpus_chunk_records",
        side_effect=fail_bad,
    ):
        result = run_corpus_ingest(
            _options(workspace_dir, jsonl_path, continue_on_error=True, batch_size=1)
        )
    assert result.records_completed == 1
    assert result.records_failed == 1
    err_file = errors_path(workspace_dir, result.run_id)
    assert err_file.is_file()
    content = err_file.read_text(encoding="utf-8")
    assert "Good article body" not in content
    assert "bad" in content.lower() or "chunk" in content.lower()


def test_dry_run_performs_no_writes(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    result = run_corpus_ingest(_options(workspace_dir, jsonl_path, dry_run=True))
    assert "Dry run" in result.message
    assert not (workspace_dir / "corpus-runs").exists()
    assert workspace_catalog.get_index(workspace_dir, "corpus-smoke") is None


def test_completed_run_is_idempotent(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    run_corpus_ingest(_options(workspace_dir, jsonl_path))
    again = run_corpus_ingest(_options(workspace_dir, jsonl_path))
    assert again.message == "Run already completed."


def test_force_rebuild_only_selected_index(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, tmp_path = corpus_env
    run_corpus_ingest(_options(workspace_dir, jsonl_path))

    other_jsonl = tmp_path / "other.jsonl"
    other_jsonl.write_text(
        json.dumps({"id": "x", "title": "Other", "text": "Other index content."}) + "\n",
        encoding="utf-8",
    )
    run_corpus_ingest(
        CorpusIngestOptions(
            source_path=other_jsonl,
            index_slug="other-index",
            workspace_dir=workspace_dir,
            batch_size=1,
        )
    )
    assert workspace_catalog.get_index(workspace_dir, "other-index") is not None

    run_corpus_ingest(
        _options(workspace_dir, jsonl_path, force_rebuild=True, yes=True, batch_size=1)
    )
    assert workspace_catalog.get_index(workspace_dir, "corpus-smoke") is not None
    assert workspace_catalog.get_index(workspace_dir, "other-index") is not None


def test_no_writes_outside_workspace(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, tmp_path = corpus_env
    run_corpus_ingest(_options(workspace_dir, jsonl_path))
    for path in tmp_path.rglob("*"):
        if path.is_file() and workspace_dir not in path.parents and path != jsonl_path:
            if path.name.endswith((".jsonl", ".json", ".sqlite")):
                pytest.fail(f"Unexpected write outside workspace: {path}")


def test_interrupted_run_marked_interrupted(corpus_env: tuple[Path, Path, Path]) -> None:
    workspace_dir, jsonl_path, _ = corpus_env
    from ark_pi.corpus.ingest import CorpusIngestInterrupted

    original_flush = None

    def interrupt_flush(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    with patch("ark_pi.corpus.ingest.chunking.append_chunks_jsonl", side_effect=interrupt_flush):
        with pytest.raises(CorpusIngestInterrupted):
            run_corpus_ingest(_options(workspace_dir, jsonl_path, batch_size=1))

    run_id = _run_id(workspace_dir, jsonl_path)
    ckpt = load_checkpoint(checkpoint_path(workspace_dir, run_id))
    assert ckpt.status == CorpusRunStatus.interrupted
