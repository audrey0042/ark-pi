from pathlib import Path

from ark_pi.corpus.checkpoint import CorpusCheckpointError, load_checkpoint
from ark_pi.corpus.ingest import build_resume_command
from ark_pi.corpus.run_state import (
    checkpoint_path,
    find_latest_run_id,
    run_dir,
)
from ark_pi.corpus.types import CorpusRunStatus, CorpusStatusResult


class CorpusStatusError(Exception):
    """Raised when corpus status cannot be read."""


def get_corpus_status(
    workspace_dir: Path,
    *,
    run_id: str | None = None,
) -> CorpusStatusResult:
    resolved_run_id = run_id or find_latest_run_id(workspace_dir)
    if resolved_run_id is None:
        msg = "No corpus runs found in workspace"
        raise CorpusStatusError(msg)

    ckpt_path = checkpoint_path(workspace_dir, resolved_run_id)
    try:
        checkpoint = load_checkpoint(ckpt_path)
    except CorpusCheckpointError as exc:
        raise CorpusStatusError(str(exc)) from exc

    progress_percent: float | None = None
    if checkpoint.estimated_records and checkpoint.estimated_records > 0:
        progress_percent = round(
            100.0 * checkpoint.records_completed / checkpoint.estimated_records,
            2,
        )

    resume_command = build_resume_command(
        source=checkpoint.source,
        index_slug=checkpoint.index_slug,
        workspace_dir=workspace_dir.expanduser().resolve(),
        batch_size=checkpoint.batch_size,
        chunk_size=checkpoint.chunking_config.chunk_size,
        chunk_overlap=checkpoint.chunking_config.chunk_overlap,
        backend=checkpoint.index_backend,
        run_id=checkpoint.run_id,
    )

    return CorpusStatusResult(
        run_id=checkpoint.run_id,
        source=checkpoint.source,
        index_slug=checkpoint.index_slug,
        status=CorpusRunStatus(checkpoint.status.value),
        records_seen=checkpoint.records_seen,
        records_completed=checkpoint.records_completed,
        records_failed=checkpoint.records_failed,
        chunks_written=checkpoint.chunks_written,
        progress_percent=progress_percent,
        updated_at=checkpoint.updated_at,
        resume_command=resume_command,
        run_dir=run_dir(workspace_dir, resolved_run_id),
        index_backend=checkpoint.index_backend,
        embedding_fingerprint=checkpoint.embedding_fingerprint,
        records_embedded=checkpoint.records_embedded,
        committed_batches=checkpoint.committed_batches,
    )
