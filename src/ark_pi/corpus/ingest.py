import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ark_pi import config as ark_config
from ark_pi.corpus.checkpoint import (
    CorpusCheckpoint,
    CorpusCheckpointError,
    load_checkpoint,
    new_checkpoint,
    validate_checkpoint_compatibility,
    write_checkpoint,
)
from ark_pi.corpus.completion import CompletionLedger
from ark_pi.corpus.fingerprint import (
    derive_run_id,
    detect_source_format,
    fingerprint_source,
)
from ark_pi.corpus.run_state import (
    append_error,
    checkpoint_path,
    completion_db_path,
    run_dir,
    write_manifest,
    write_summary,
)
from ark_pi.corpus.sources import estimate_record_count, iter_corpus_documents
from ark_pi.corpus.types import (
    ChunkingConfig,
    CorpusDryRunResult,
    CorpusIngestOptions,
    CorpusIngestResult,
    CorpusRunStatus,
    CorpusSourceFormat,
)
from ark_pi.embeddings.errors import EmbeddingError
from ark_pi.embeddings.factory import create_embedder
from ark_pi.ingest import chunking
from ark_pi.ingest.pipeline import validate_output_path
from ark_pi.rag import index as rag_index
from ark_pi.rag.index import MANIFEST_FILE, IndexErrorBase
from ark_pi.rag.semantic_index import (
    EmbeddingIdentity,
    SemanticIndexCompatibilityError,
    SemanticIndexError,
    compute_embedding_fingerprint,
    identity_from_embedder,
    identity_from_manifest,
    identity_from_settings,
    validate_embedding_compatibility,
)
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import index_paths, validate_index_name


class CorpusIngestError(Exception):
    """Raised for fatal corpus ingest failures."""


class CorpusIngestInterrupted(Exception):
    """Raised when ingestion is interrupted by the operator."""

    def __init__(self, result: CorpusIngestResult) -> None:
        super().__init__(result.message)
        self.result = result


_MIN_FREE_BYTES = 50 * 1024 * 1024


def build_resume_command(
    *,
    source: str,
    index_slug: str,
    workspace_dir: Path,
    batch_size: int,
    chunk_size: int,
    chunk_overlap: int,
    backend: str,
    run_id: str,
    embedding_backend: str | None = None,
    embedding_model_path: Path | None = None,
    allow_network: bool | None = None,
) -> str:
    parts = [
        "ark corpus ingest",
        f'"{source}"',
        f"--index {index_slug}",
        f"--workspace-dir {workspace_dir}",
        f"--batch-size {batch_size}",
        f"--chunk-size {chunk_size}",
        f"--chunk-overlap {chunk_overlap}",
        f"--backend {backend}",
        f"--run-id {run_id}",
        "--resume",
    ]
    if backend == "chroma":
        if embedding_backend is not None:
            parts.append(f"--embedding-backend {embedding_backend}")
        if embedding_model_path is not None:
            parts.append(f"--embedding-model-path {embedding_model_path}")
        if allow_network:
            parts.append("--allow-network")
    return " ".join(parts)


def _check_disk_space(workspace_dir: Path) -> None:
    inspect_path = workspace_dir if workspace_dir.exists() else workspace_dir.parent
    try:
        usage = shutil.disk_usage(inspect_path)
    except OSError as exc:
        msg = f"Could not inspect disk space for {inspect_path}: {exc}"
        raise CorpusIngestError(msg) from exc
    if usage.free < _MIN_FREE_BYTES:
        msg = (
            f"Insufficient disk space at {inspect_path}: "
            f"{usage.free} bytes free (minimum {_MIN_FREE_BYTES} required)"
        )
        raise CorpusIngestError(msg)


def _validate_backend(backend: str) -> None:
    if backend not in {"simple", "chroma"}:
        msg = f"Unsupported corpus ingest backend: {backend!r}"
        raise CorpusIngestError(msg)


@dataclass(frozen=True)
class _SemanticRunContext:
    embedder: object
    identity: EmbeddingIdentity
    fingerprint: str
    collection_name: str
    embedding_batch_size: int
    embedding_backend: str


def _resolve_ingest_settings(options: CorpusIngestOptions) -> ark_config.ArkSettings:
    settings = ark_config.get_settings()
    updates: dict[str, object] = {}
    if options.embedding_backend is not None:
        updates["embedding_backend"] = options.embedding_backend
    if options.embedding_model_path is not None:
        updates["embedding_model_path"] = options.embedding_model_path
    if options.allow_network is not None:
        updates["embedding_allow_network"] = options.allow_network
    if options.embedding_batch_size is not None:
        updates["embedding_batch_size"] = options.embedding_batch_size
    if updates:
        settings = settings.model_copy(update=updates)
    return settings


def _passive_embedding_fingerprint(options: CorpusIngestOptions) -> str | None:
    if options.backend != "chroma":
        return None
    settings = _resolve_ingest_settings(options)
    identity = identity_from_settings(
        settings,
        embedding_backend=options.embedding_backend,
        model_path=options.embedding_model_path,
    )
    return compute_embedding_fingerprint(identity)


def _resolve_semantic_run_context(options: CorpusIngestOptions) -> _SemanticRunContext:
    settings = _resolve_ingest_settings(options)
    try:
        embedder = create_embedder(
            settings,
            allow_network_override=options.allow_network,
            model_path_override=options.embedding_model_path,
        )
    except EmbeddingError as exc:
        raise CorpusIngestError(str(exc)) from exc

    identity = identity_from_embedder(embedder, settings)
    fingerprint = compute_embedding_fingerprint(identity)
    collection_name = options.collection_name or settings.collection_name
    return _SemanticRunContext(
        embedder=embedder,
        identity=identity,
        fingerprint=fingerprint,
        collection_name=collection_name,
        embedding_batch_size=settings.embedding_batch_size,
        embedding_backend=embedder.backend_name,
    )


def _validate_index_embedding_compatibility(
    index_dir: Path,
    identity: EmbeddingIdentity,
) -> None:
    manifest_path = index_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        return
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid index manifest in {manifest_path}: {exc.msg}"
        raise CorpusIngestError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"Invalid index manifest in {manifest_path}"
        raise CorpusIngestError(msg)
    existing = identity_from_manifest(raw)
    if existing is None:
        return
    try:
        validate_embedding_compatibility(existing, identity)
    except SemanticIndexCompatibilityError as exc:
        raise CorpusIngestError(str(exc)) from exc


def _ingest_result_from_checkpoint(
    *,
    run_id: str,
    index_slug: str,
    source: str,
    source_format: CorpusSourceFormat,
    checkpoint: CorpusCheckpoint,
    ckpt_path: Path,
    workspace_dir: Path,
    resume_command: str,
    started: float,
    message: str,
    partial: bool = False,
    semantic: _SemanticRunContext | None = None,
    records_skipped: int = 0,
) -> CorpusIngestResult:
    return CorpusIngestResult(
        run_id=run_id,
        index_slug=index_slug,
        source=source,
        source_format=source_format,
        status=CorpusRunStatus(checkpoint.status.value),
        records_seen=checkpoint.records_seen,
        records_completed=checkpoint.records_completed,
        records_failed=checkpoint.records_failed,
        chunks_written=checkpoint.chunks_written,
        run_dir=run_dir(workspace_dir, run_id),
        checkpoint_path=ckpt_path,
        resume_command=resume_command,
        elapsed_seconds=time.monotonic() - started,
        partial=partial,
        message=message,
        index_backend=checkpoint.index_backend,
        records_embedded=checkpoint.records_embedded,
        records_skipped=records_skipped,
        committed_batches=checkpoint.committed_batches,
        embedding_fingerprint=checkpoint.embedding_fingerprint,
        embedding_backend=semantic.embedding_backend if semantic is not None else None,
    )


def _resolve_options(options: CorpusIngestOptions) -> tuple[Path, str, ChunkingConfig]:
    source_path = validate_output_path(options.source_path, label="source_path")
    workspace_dir = validate_output_path(options.workspace_dir, label="workspace_dir")
    index_slug = validate_index_name(options.index_slug)
    if options.batch_size <= 0:
        msg = "batch-size must be greater than 0"
        raise CorpusIngestError(msg)
    chunking.validate_chunk_params(options.chunk_size, options.chunk_overlap)
    _validate_backend(options.backend)
    chunking_config = ChunkingConfig(
        chunk_size=options.chunk_size,
        chunk_overlap=options.chunk_overlap,
    )
    return source_path, index_slug, chunking_config


def _force_rebuild(
    workspace_dir: Path,
    run_id: str,
    index_slug: str,
    *,
    yes: bool,
) -> None:
    if not yes:
        msg = "Refusing --force-rebuild without --yes"
        raise CorpusIngestError(msg)
    run_path = run_dir(workspace_dir, run_id)
    if run_path.exists():
        shutil.rmtree(run_path)
    existing = workspace_catalog.get_index(workspace_dir, index_slug)
    if existing is not None:
        workspace_catalog.delete_index(workspace_dir, index_slug)


def run_corpus_dry_run(options: CorpusIngestOptions) -> CorpusDryRunResult:
    source_path, index_slug, chunking_config = _resolve_options(options)
    source_format = detect_source_format(source_path)
    source_fp = fingerprint_source(source_path)
    embedding_fingerprint = _passive_embedding_fingerprint(options)
    settings = _resolve_ingest_settings(options)
    embedding_backend = (
        options.embedding_backend or settings.embedding_backend
        if options.backend == "chroma"
        else None
    )
    run_id = options.run_id or derive_run_id(
        source_fingerprint=source_fp,
        index_slug=index_slug,
        chunk_size=chunking_config.chunk_size,
        chunk_overlap=chunking_config.chunk_overlap,
        backend=options.backend,
        embedding_fingerprint=embedding_fingerprint,
    )
    estimated = estimate_record_count(source_path, source_format)
    return CorpusDryRunResult(
        run_id=run_id,
        index_slug=index_slug,
        source=str(source_path),
        source_format=source_format,
        source_fingerprint=source_fp,
        estimated_records=estimated,
        run_dir=run_dir(options.workspace_dir, run_id),
        backend=options.backend,
        batch_size=options.batch_size,
        chunking_config=chunking_config,
        embedding_fingerprint=embedding_fingerprint,
        embedding_backend=embedding_backend,
    )


def run_corpus_ingest(
    options: CorpusIngestOptions,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> CorpusIngestResult:
    started = time.monotonic()
    source_path, index_slug, chunking_config = _resolve_options(options)
    workspace_dir = options.workspace_dir.expanduser().resolve()
    source_format = detect_source_format(source_path)
    source_fp = fingerprint_source(source_path)
    semantic: _SemanticRunContext | None = None
    embedding_fingerprint: str | None = None
    if options.backend == "chroma":
        semantic = _resolve_semantic_run_context(options)
        embedding_fingerprint = semantic.fingerprint
    run_id = options.run_id or derive_run_id(
        source_fingerprint=source_fp,
        index_slug=index_slug,
        chunk_size=chunking_config.chunk_size,
        chunk_overlap=chunking_config.chunk_overlap,
        backend=options.backend,
        embedding_fingerprint=embedding_fingerprint,
    )

    settings = _resolve_ingest_settings(options)
    resume_embedding_backend = (
        options.embedding_backend or settings.embedding_backend
        if options.backend == "chroma"
        else None
    )

    if options.dry_run:
        dry = run_corpus_dry_run(options)
        return CorpusIngestResult(
            run_id=dry.run_id,
            index_slug=dry.index_slug,
            source=dry.source,
            source_format=dry.source_format,
            status=CorpusRunStatus.planned,
            records_seen=0,
            records_completed=0,
            records_failed=0,
            chunks_written=0,
            run_dir=dry.run_dir,
            checkpoint_path=checkpoint_path(workspace_dir, dry.run_id),
            resume_command=build_resume_command(
                source=dry.source,
                index_slug=dry.index_slug,
                workspace_dir=workspace_dir,
                batch_size=options.batch_size,
                chunk_size=chunking_config.chunk_size,
                chunk_overlap=chunking_config.chunk_overlap,
                backend=options.backend,
                run_id=dry.run_id,
                embedding_backend=resume_embedding_backend,
                embedding_model_path=options.embedding_model_path,
                allow_network=options.allow_network,
            ),
            elapsed_seconds=time.monotonic() - started,
            message="Dry run completed; no writes performed.",
            index_backend=options.backend,
            embedding_fingerprint=dry.embedding_fingerprint,
            embedding_backend=dry.embedding_backend,
        )

    if options.force_rebuild:
        _force_rebuild(workspace_dir, run_id, index_slug, yes=options.yes)

    _check_disk_space(workspace_dir)

    ckpt_path = checkpoint_path(workspace_dir, run_id)
    estimated = estimate_record_count(source_path, source_format)
    resume_command = build_resume_command(
        source=str(source_path),
        index_slug=index_slug,
        workspace_dir=workspace_dir,
        batch_size=options.batch_size,
        chunk_size=chunking_config.chunk_size,
        chunk_overlap=chunking_config.chunk_overlap,
        backend=options.backend,
        run_id=run_id,
        embedding_backend=resume_embedding_backend,
        embedding_model_path=options.embedding_model_path,
        allow_network=options.allow_network,
    )

    if options.resume:
        if not ckpt_path.is_file():
            msg = f"No checkpoint found for run {run_id!r}; omit --resume to start fresh"
            raise CorpusIngestError(msg)
        try:
            checkpoint = load_checkpoint(ckpt_path)
            validate_checkpoint_compatibility(
                checkpoint,
                source_fingerprint=source_fp.fingerprint,
                index_slug=index_slug,
                index_backend=options.backend,
                chunking_config=chunking_config,
                embedding_fingerprint=embedding_fingerprint,
            )
        except CorpusCheckpointError as exc:
            raise CorpusIngestError(str(exc)) from exc
        if checkpoint.status == CorpusRunStatus.completed:
            return _ingest_result_from_checkpoint(
                run_id=run_id,
                index_slug=index_slug,
                source=str(source_path),
                source_format=source_format,
                checkpoint=checkpoint,
                ckpt_path=ckpt_path,
                workspace_dir=workspace_dir,
                resume_command=resume_command,
                started=started,
                message="Run already completed.",
                semantic=semantic,
            )
    else:
        if ckpt_path.is_file() and not options.force_rebuild:
            existing = load_checkpoint(ckpt_path)
            if existing.status == CorpusRunStatus.completed:
                return _ingest_result_from_checkpoint(
                    run_id=run_id,
                    index_slug=index_slug,
                    source=str(source_path),
                    source_format=source_format,
                    checkpoint=existing,
                    ckpt_path=ckpt_path,
                    workspace_dir=workspace_dir,
                    resume_command=resume_command,
                    started=started,
                    message="Run already completed.",
                    semantic=semantic,
                )
            msg = (
                f"Corpus run {run_id!r} already exists with status {existing.status.value}. "
                "Use --resume to continue or --force-rebuild --yes to start over."
            )
            raise CorpusIngestError(msg)

        run_dir(workspace_dir, run_id).mkdir(parents=True, exist_ok=True)
        write_manifest(
            workspace_dir,
            run_id,
            source=str(source_path),
            source_format=source_format,
            source_fingerprint=source_fp,
            index_slug=index_slug,
            backend=options.backend,
            batch_size=options.batch_size,
            chunk_size=chunking_config.chunk_size,
            chunk_overlap=chunking_config.chunk_overlap,
        )
        checkpoint = new_checkpoint(
            run_id=run_id,
            source=str(source_path),
            source_format=source_format,
            source_fingerprint=source_fp.fingerprint,
            index_slug=index_slug,
            index_backend=options.backend,
            chunking_config=chunking_config,
            batch_size=options.batch_size,
            estimated_records=estimated,
            embedding_fingerprint=embedding_fingerprint,
        )
        write_checkpoint(ckpt_path, checkpoint)

    chunks_path, index_dir = index_paths(workspace_dir, index_slug)
    if semantic is not None:
        try:
            _validate_index_embedding_compatibility(index_dir, semantic.identity)
        except CorpusIngestError:
            raise
        except SemanticIndexError as exc:
            raise CorpusIngestError(str(exc)) from exc

    if progress_callback:
        progress_callback(
            f"Run {run_id} -> index {index_slug} | checkpoint: {ckpt_path}"
        )

    partial = False
    interrupted = False
    records_skipped = 0

    try:
        with CompletionLedger(completion_db_path(workspace_dir, run_id)) as ledger:
            checkpoint = load_checkpoint(ckpt_path)
            checkpoint.status = CorpusRunStatus.running
            checkpoint.updated_at = workspace_catalog.utc_now_iso()
            write_checkpoint(ckpt_path, checkpoint)

            batch_records: list[dict[str, object]] = []
            batch_documents: list[tuple[str, str]] = []
            batch_positions: list[int] = []
            source_count = ledger.count()

            def flush_batch() -> None:
                nonlocal checkpoint, partial, source_count
                if not batch_records:
                    return
                chunking.append_chunks_jsonl(batch_records, chunks_path)
                try:
                    if options.backend == "chroma":
                        assert semantic is not None
                        stats = rag_index.append_to_index(
                            batch_records,
                            index_dir,
                            backend=options.backend,
                            source_chunks=str(chunks_path),
                            embedder=semantic.embedder,
                            embedding_identity=semantic.identity,
                            collection_name=semantic.collection_name,
                            embedding_batch_size=semantic.embedding_batch_size,
                        )
                        checkpoint.records_embedded += len(batch_records)
                    else:
                        stats = rag_index.append_to_index(
                            batch_records,
                            index_dir,
                            backend=options.backend,
                            source_chunks=str(chunks_path),
                        )
                except (EmbeddingError, SemanticIndexError, IndexErrorBase) as exc:
                    raise CorpusIngestError(str(exc)) from exc
                for doc_id, digest in batch_documents:
                    ledger.mark_completed(doc_id, digest)
                ledger.commit()

                checkpoint.records_completed += len(batch_documents)
                checkpoint.chunks_written += len(batch_records)
                checkpoint.last_completed_position = batch_positions[-1]
                checkpoint.committed_batches += 1
                checkpoint.updated_at = workspace_catalog.utc_now_iso()
                write_checkpoint(ckpt_path, checkpoint)

                source_count = ledger.count()
                now = workspace_catalog.utc_now_iso()
                existing = workspace_catalog.get_index(workspace_dir, index_slug)
                created_at = existing.created_at if existing is not None else now
                entry = workspace_catalog.CatalogIndexEntry(
                    name=index_slug,
                    slug=index_slug,
                    backend=options.backend,
                    chunks_path=str(chunks_path),
                    index_dir=str(index_dir),
                    chunk_count=stats.chunk_count,
                    source_count=source_count,
                    created_at=created_at,
                    updated_at=now,
                    corpus_run_id=run_id,
                    source_fingerprint=source_fp.fingerprint,
                )
                workspace_catalog.upsert_index(workspace_dir, entry)

                if progress_callback:
                    progress_callback(
                        f"Batch complete: {checkpoint.records_completed} documents, "
                        f"{checkpoint.chunks_written} chunks"
                    )

                batch_records.clear()
                batch_documents.clear()
                batch_positions.clear()

            try:
                document_iter = iter_corpus_documents(source_path, source_format)
            except ValueError as exc:
                raise CorpusIngestError(str(exc)) from exc

            try:
                for document in document_iter:
                    checkpoint.records_seen += 1

                    existing_digest = ledger.get_digest(document.document_id)
                    if existing_digest is not None:
                        if existing_digest != document.content_digest:
                            msg = (
                                f"Document {document.document_id!r} content changed since last "
                                "completion. Use --force-rebuild --yes to re-ingest."
                            )
                            raise CorpusIngestError(msg)
                        records_skipped += 1
                        continue

                    try:
                        doc_chunks = chunking.make_corpus_chunk_records(
                            document.document_id,
                            document.title,
                            document.source,
                            document.text,
                            chunking_config.chunk_size,
                            chunking_config.chunk_overlap,
                        )
                    except ValueError as exc:
                        if options.continue_on_error:
                            checkpoint.records_failed += 1
                            partial = True
                            append_error(
                                workspace_dir,
                                run_id,
                                document_id=document.document_id,
                                position=document.position,
                                error_type="chunk_error",
                                message=str(exc),
                            )
                            continue
                        raise CorpusIngestError(str(exc)) from exc

                    if not doc_chunks:
                        continue

                    batch_records.extend(doc_chunks)
                    batch_documents.append((document.document_id, document.content_digest))
                    batch_positions.append(document.position)

                    if len(batch_documents) >= options.batch_size:
                        flush_batch()
            except ValueError as exc:
                raise CorpusIngestError(str(exc)) from exc

            flush_batch()

            final_status = CorpusRunStatus.completed
            if checkpoint.records_failed > 0:
                partial = True
                final_status = CorpusRunStatus.failed if not options.continue_on_error else CorpusRunStatus.completed

            checkpoint.status = final_status
            checkpoint.updated_at = workspace_catalog.utc_now_iso()
            write_checkpoint(ckpt_path, checkpoint)

    except KeyboardInterrupt:
        interrupted = True
        checkpoint = load_checkpoint(ckpt_path)
        checkpoint.status = CorpusRunStatus.interrupted
        checkpoint.updated_at = workspace_catalog.utc_now_iso()
        write_checkpoint(ckpt_path, checkpoint)
        elapsed = time.monotonic() - started
        result = _ingest_result_from_checkpoint(
            run_id=run_id,
            index_slug=index_slug,
            source=str(source_path),
            source_format=source_format,
            checkpoint=checkpoint,
            ckpt_path=ckpt_path,
            workspace_dir=workspace_dir,
            resume_command=resume_command,
            started=started,
            message=f"Interrupted. Resume with: {resume_command}",
            partial=True,
            semantic=semantic,
            records_skipped=records_skipped,
        )
        raise CorpusIngestInterrupted(result) from None

    checkpoint = load_checkpoint(ckpt_path)
    elapsed = time.monotonic() - started
    write_summary(
        workspace_dir,
        run_id,
        status=checkpoint.status,
        records_seen=checkpoint.records_seen,
        records_completed=checkpoint.records_completed,
        records_failed=checkpoint.records_failed,
        chunks_written=checkpoint.chunks_written,
        elapsed_seconds=elapsed,
    )

    return _ingest_result_from_checkpoint(
        run_id=run_id,
        index_slug=index_slug,
        source=str(source_path),
        source_format=source_format,
        checkpoint=checkpoint,
        ckpt_path=ckpt_path,
        workspace_dir=workspace_dir,
        resume_command=resume_command,
        started=started,
        partial=partial or interrupted,
        message=(
            "Corpus ingest completed."
            if checkpoint.status == CorpusRunStatus.completed
            else "Corpus ingest finished with failures."
        ),
        semantic=semantic,
        records_skipped=records_skipped,
    )
