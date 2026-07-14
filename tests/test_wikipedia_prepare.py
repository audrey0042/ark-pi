"""Service-level tests for Wikipedia dump preparation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ark_pi.corpus.fingerprint import sha256_file
from ark_pi.corpus.sources import iter_jsonl_documents
from ark_pi.corpus.wikipedia import (
    PrepareWikipediaOptions,
    WikipediaPrepareError,
    WikipediaPrepareInterrupted,
    WikipediaPrepareStatus,
    checkpoint_path,
    manifest_path,
    partial_output_path,
    run_prepare_wikipedia,
    run_prepare_wikipedia_dry_run,
)
from ark_pi.corpus.ingest import run_corpus_ingest
from ark_pi.corpus.types import CorpusIngestOptions
from ark_pi.rag import index as rag_index
from tests.mediawiki_fixtures import ensure_compressed_fixtures


@pytest.fixture
def prepare_env(tmp_path: Path) -> dict[str, Path]:
    paths = ensure_compressed_fixtures(tmp_path)
    output = tmp_path / "articles.jsonl"
    return {**paths, "output": output, "workspace": tmp_path / "workspace"}


def _options(
    prepare_env: dict[str, Path],
    **overrides: object,
) -> PrepareWikipediaOptions:
    base = {
        "input_path": prepare_env["plain"],
        "output_path": prepare_env["output"],
        "project": "simplewiki",
        "min_text_chars": 50,
        "checkpoint_every": 1,
    }
    base.update(overrides)
    return PrepareWikipediaOptions(**base)


def test_dry_run_writes_nothing(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia_dry_run(_options(prepare_env, dry_run=True))
    assert "Dry run" in result.message
    assert not prepare_env["output"].exists()
    assert not partial_output_path(prepare_env["output"]).exists()


def test_plain_xml_emits_main_namespace_article(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(_options(prepare_env))
    assert result.status == WikipediaPrepareStatus.completed
    assert result.records_emitted == 1
    assert prepare_env["output"].is_file()
    records = list(iter_jsonl_documents(prepare_env["output"]))
    assert len(records) == 1
    assert records[0].title == "Fixture article"
    assert "fixture article phrase" in records[0].text


def test_gzip_and_bzip2_inputs(tmp_path: Path) -> None:
    paths = ensure_compressed_fixtures(tmp_path)
    for key in ("gzip", "bzip2"):
        output = tmp_path / f"{key}.jsonl"
        result = run_prepare_wikipedia(
            PrepareWikipediaOptions(
                input_path=paths[key],
                output_path=output,
                min_text_chars=50,
                checkpoint_every=1,
            )
        )
        assert result.records_emitted == 1


def test_namespace_filter_skips_talk_pages(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(_options(prepare_env))
    assert result.namespace_pages_skipped >= 2


def test_custom_namespace_filter(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(
        _options(prepare_env, namespace_filters=(1,), min_text_chars=10)
    )
    assert result.records_emitted == 1
    records = list(iter_jsonl_documents(prepare_env["output"]))
    assert records[0].title == "Talk:Fixture article"


def test_redirects_skipped_by_default(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(_options(prepare_env))
    assert result.redirects_skipped == 1


def test_include_redirects_emits_metadata(prepare_env: dict[str, Path]) -> None:
    output = prepare_env["output"].with_name("with-redirects.jsonl")
    run_prepare_wikipedia(
        _options(
            prepare_env,
            output_path=output,
            include_redirects=True,
            min_text_chars=10,
        )
    )
    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    redirect = next(record for record in records if record["metadata"]["page_id"] == 1004)
    assert redirect["metadata"]["redirect"] is True
    assert redirect["metadata"]["redirect_target"] == "Fixture article"


def test_record_schema_and_url(prepare_env: dict[str, Path]) -> None:
    run_prepare_wikipedia(_options(prepare_env))
    payload = json.loads(prepare_env["output"].read_text(encoding="utf-8").strip())
    assert payload["id"] == "simplewiki:page:1001"
    assert payload["source"] == "simplewiki"
    assert payload["url"] == "https://simple.wikipedia.org/wiki/Fixture_article"
    assert payload["metadata"]["page_id"] == 1001
    assert payload["metadata"]["revision_id"] == 5001
    assert payload["metadata"]["normalizer"] == "ark-pi-wikipedia-v1"


def test_short_pages_skipped(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(_options(prepare_env, min_text_chars=100))
    assert result.records_emitted == 1
    assert result.short_pages_skipped >= 1


def test_limit_stops_after_requested_count(prepare_env: dict[str, Path]) -> None:
    result = run_prepare_wikipedia(
        _options(prepare_env, include_redirects=True, min_text_chars=10, limit=2)
    )
    assert result.records_emitted == 2


def test_existing_output_requires_force(prepare_env: dict[str, Path]) -> None:
    run_prepare_wikipedia(_options(prepare_env))
    with pytest.raises(WikipediaPrepareError, match="already exists"):
        run_prepare_wikipedia(_options(prepare_env))


def test_force_requires_yes(prepare_env: dict[str, Path]) -> None:
    run_prepare_wikipedia(_options(prepare_env))
    with pytest.raises(WikipediaPrepareError, match="--force without --yes"):
        run_prepare_wikipedia(_options(prepare_env, force=True))


def test_checksum_mismatch_fails(prepare_env: dict[str, Path]) -> None:
    with pytest.raises(WikipediaPrepareError, match="SHA-256 checksum mismatch"):
        run_prepare_wikipedia(
            _options(prepare_env, expected_sha256="0" * 64)
        )


def test_manifest_and_attribution_created(prepare_env: dict[str, Path]) -> None:
    run_prepare_wikipedia(_options(prepare_env))
    manifest = json.loads(manifest_path(prepare_env["output"]).read_text(encoding="utf-8"))
    assert manifest["schema_name"] == "ark-pi-wikipedia-corpus-manifest"
    assert manifest["records_emitted"] == 1
    assert manifest["dump_sha256"] == sha256_file(prepare_env["plain"])
    assert manifest["output_sha256"] == sha256_file(prepare_env["output"])
    attribution = prepare_env["output"].with_suffix(".jsonl.ATTRIBUTION.txt")
    assert attribution.is_file()
    assert "simplewiki" in attribution.read_text(encoding="utf-8")


def test_keyboard_interrupt_creates_checkpoint(prepare_env: dict[str, Path]) -> None:
    options = _options(prepare_env, checkpoint_every=1)
    with patch(
        "ark_pi.corpus.wikipedia.iter_mediawiki_pages",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(WikipediaPrepareInterrupted):
            run_prepare_wikipedia(options)
    ckpt = json.loads(checkpoint_path(prepare_env["output"]).read_text(encoding="utf-8"))
    assert ckpt["status"] == "interrupted"


from ark_pi.workspace.paths import index_paths


def _simulate_interrupted_run(
    prepare_env: dict[str, Path],
    *,
    pages_scanned: int,
    records_emitted: int,
) -> None:
    run_prepare_wikipedia(_options(prepare_env))
    output = prepare_env["output"]
    partial = partial_output_path(output)
    ckpt = checkpoint_path(output)
    lines = output.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip()][:records_emitted]
    partial.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    output.unlink()
    data = {
        "schema_name": "ark-pi-wikipedia-preparation-checkpoint",
        "schema_version": 1,
        "input_path": str(prepare_env["plain"].resolve()),
        "input_size": prepare_env["plain"].stat().st_size,
        "input_fingerprint": sha256_file(prepare_env["plain"]),
        "output_path": str(output),
        "project": "simplewiki",
        "base_url": "https://simple.wikipedia.org/wiki/",
        "namespace_filters": [0],
        "include_redirects": False,
        "min_text_chars": 50,
        "normalizer_version": "ark-pi-wikipedia-v1",
        "pages_scanned": pages_scanned,
        "records_emitted": records_emitted,
        "redirects_skipped": 1,
        "namespace_pages_skipped": 2,
        "short_pages_skipped": 1,
        "page_errors": 0,
        "partial_output_bytes": partial.stat().st_size,
        "status": "interrupted",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }
    ckpt.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_resume_without_duplicates(prepare_env: dict[str, Path]) -> None:
    _simulate_interrupted_run(prepare_env, pages_scanned=2, records_emitted=1)

    result = run_prepare_wikipedia(_options(prepare_env, resume=True))
    assert result.records_emitted == 1
    assert len(list(iter_jsonl_documents(prepare_env["output"]))) == 1


def test_resume_rejects_changed_fingerprint(prepare_env: dict[str, Path]) -> None:
    _simulate_interrupted_run(prepare_env, pages_scanned=2, records_emitted=1)

    other = prepare_env["plain"].with_name("other.xml")
    other.write_text(prepare_env["plain"].read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(WikipediaPrepareError, match="Incompatible checkpoint"):
        run_prepare_wikipedia(
            _options(prepare_env, input_path=other, resume=True)
        )


def test_incomplete_partial_line_truncated(prepare_env: dict[str, Path]) -> None:
    _simulate_interrupted_run(prepare_env, pages_scanned=2, records_emitted=1)
    partial = partial_output_path(prepare_env["output"])
    partial.write_text(partial.read_text(encoding="utf-8") + '{"incomplete":', encoding="utf-8")

    result = run_prepare_wikipedia(_options(prepare_env, resume=True))
    assert result.records_emitted == 1


def test_continue_on_page_error_partial_status(
    prepare_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ark_pi.corpus import wikipedia as wikipedia_module

    original = wikipedia_module.ArkPiWikipediaV1Normalizer.normalize

    def flaky(self: object, wikitext: str) -> object:
        if "fixture article phrase" in wikitext:
            msg = "Cleaner failed"
            raise ValueError(msg)
        return original(self, wikitext)

    monkeypatch.setattr(
        wikipedia_module.ArkPiWikipediaV1Normalizer,
        "normalize",
        flaky,
    )
    result = run_prepare_wikipedia(
        _options(prepare_env, continue_on_page_error=True, min_text_chars=10)
    )
    assert result.page_errors >= 1
    assert result.partial is True
    errors = prepare_env["output"].with_suffix(".jsonl.errors.jsonl")
    assert errors.is_file()
    error_line = errors.read_text(encoding="utf-8").strip()
    assert "fixture article phrase" not in error_line


def test_end_to_end_prepare_ingest_search(prepare_env: dict[str, Path]) -> None:
    workspace = prepare_env["workspace"]
    workspace.mkdir()
    run_prepare_wikipedia(_options(prepare_env))
    ingest = run_corpus_ingest(
        CorpusIngestOptions(
            source_path=prepare_env["output"],
            index_slug="simplewiki-fixture",
            workspace_dir=workspace,
            batch_size=1,
        )
    )
    assert ingest.records_completed == 1
    _, index_dir = index_paths(workspace, "simplewiki-fixture")
    hits = rag_index.search_index(
        index_dir,
        "fixture article phrase",
        limit=3,
    ).results
    assert hits
    assert any("fixture article phrase" in hit.text.lower() for hit in hits)
