"""Wikipedia dump preparation orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ark_pi.corpus.fingerprint import sha1_file, sha256_file
from ark_pi.corpus.mediawiki_xml import (
    MediaWikiPage,
    MediaWikiXmlError,
    iter_mediawiki_pages,
    open_dump_stream,
    validate_dump_path,
)
from ark_pi.corpus.wikitext import (
    NORMALIZER_VERSION,
    ArkPiWikipediaV1Normalizer,
    redirect_text,
)
from ark_pi.ingest.pipeline import validate_output_path
from ark_pi.workspace.catalog import utc_now_iso

CHECKPOINT_SCHEMA_NAME = "ark-pi-wikipedia-preparation-checkpoint"
CHECKPOINT_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_NAME = "ark-pi-wikipedia-corpus-manifest"
MANIFEST_SCHEMA_VERSION = 1

DEFAULT_PROJECT = "simplewiki"
DEFAULT_BASE_URL = "https://simple.wikipedia.org/wiki/"
DEFAULT_MIN_TEXT_CHARS = 100
DEFAULT_CHECKPOINT_EVERY = 1000
DEFAULT_INGEST_BATCH_SIZE = 100

LICENSE_NOTICE_URLS = {
    "simplewiki": "https://simple.wikipedia.org/wiki/Wikipedia:Copyrights",
    "wikipedia": "https://en.wikipedia.org/wiki/Wikipedia:Copyrights",
}

_MIN_FREE_BYTES = 50 * 1024 * 1024


class WikipediaPrepareStatus(str, Enum):
    planned = "planned"
    running = "running"
    interrupted = "interrupted"
    failed = "failed"
    completed = "completed"


class WikipediaPrepareError(Exception):
    """Fatal preparation failure."""


class WikipediaPrepareInterrupted(Exception):
    """Preparation interrupted by operator."""

    def __init__(self, result: PrepareWikipediaResult) -> None:
        super().__init__(result.message)
        self.result = result


@dataclass(frozen=True)
class InputFingerprint:
    normalized_path: str
    size_bytes: int
    sha256: str
    sha1: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "normalized_path": self.normalized_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.sha1 is not None:
            payload["sha1"] = self.sha1
        return payload


@dataclass
class WikipediaCheckpoint:
    schema_name: str
    schema_version: int
    input_path: str
    input_size: int
    input_fingerprint: str
    output_path: str
    project: str
    base_url: str
    namespace_filters: list[int]
    include_redirects: bool
    min_text_chars: int
    normalizer_version: str
    pages_scanned: int
    records_emitted: int
    redirects_skipped: int
    namespace_pages_skipped: int
    short_pages_skipped: int
    page_errors: int
    partial_output_bytes: int
    status: WikipediaPrepareStatus
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "input_path": self.input_path,
            "input_size": self.input_size,
            "input_fingerprint": self.input_fingerprint,
            "output_path": self.output_path,
            "project": self.project,
            "base_url": self.base_url,
            "namespace_filters": self.namespace_filters,
            "include_redirects": self.include_redirects,
            "min_text_chars": self.min_text_chars,
            "normalizer_version": self.normalizer_version,
            "pages_scanned": self.pages_scanned,
            "records_emitted": self.records_emitted,
            "redirects_skipped": self.redirects_skipped,
            "namespace_pages_skipped": self.namespace_pages_skipped,
            "short_pages_skipped": self.short_pages_skipped,
            "page_errors": self.page_errors,
            "partial_output_bytes": self.partial_output_bytes,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PrepareWikipediaOptions:
    input_path: Path
    output_path: Path
    project: str = DEFAULT_PROJECT
    base_url: str = DEFAULT_BASE_URL
    source_url: str | None = None
    dump_date: str | None = None
    namespace_filters: tuple[int, ...] = (0,)
    include_redirects: bool = False
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS
    limit: int | None = None
    resume: bool = False
    force: bool = False
    yes: bool = False
    checkpoint_every: int = DEFAULT_CHECKPOINT_EVERY
    continue_on_page_error: bool = False
    dry_run: bool = False
    expected_sha1: str | None = None
    expected_sha256: str | None = None
    checksum_file: Path | None = None


@dataclass(frozen=True)
class PrepareWikipediaDryRunResult:
    input_path: str
    output_path: str
    project: str
    namespace_filters: tuple[int, ...]
    input_fingerprint: InputFingerprint
    checkpoint_path: Path
    partial_output_path: Path
    manifest_path: Path
    message: str


@dataclass(frozen=True)
class PrepareWikipediaResult:
    input_path: str
    output_path: str
    project: str
    status: WikipediaPrepareStatus
    pages_scanned: int
    records_emitted: int
    redirects_skipped: int
    namespace_pages_skipped: int
    short_pages_skipped: int
    page_errors: int
    checkpoint_path: Path
    manifest_path: Path | None
    attribution_path: Path | None
    resume_command: str
    ingest_command: str
    elapsed_seconds: float
    partial: bool = False
    message: str = ""


def partial_output_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".partial")


def checkpoint_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".checkpoint.json")


def errors_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".errors.jsonl")


def manifest_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".manifest.json")


def manifest_partial_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".manifest.partial.json")


def attribution_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".ATTRIBUTION.txt")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _append_error(output_path: Path, payload: dict[str, Any]) -> None:
    err_path = errors_path(output_path)
    err_path.parent.mkdir(parents=True, exist_ok=True)
    with err_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _check_disk_space(path: Path) -> None:
    inspect_path = path.parent if path.parent.exists() else path.parent.parent
    try:
        usage = shutil.disk_usage(inspect_path)
    except OSError as exc:
        msg = f"Could not inspect disk space for {inspect_path}: {exc}"
        raise WikipediaPrepareError(msg) from exc
    if usage.free < _MIN_FREE_BYTES:
        msg = (
            f"Insufficient disk space at {inspect_path}: "
            f"{usage.free} bytes free (minimum {_MIN_FREE_BYTES} required)"
        )
        raise WikipediaPrepareError(msg)


def fingerprint_input(path: Path, *, compute_sha1: bool = False) -> InputFingerprint:
    resolved = validate_dump_path(path)
    stat = resolved.stat()
    sha256 = sha256_file(resolved)
    sha1 = sha1_file(resolved) if compute_sha1 else None
    return InputFingerprint(
        normalized_path=str(resolved),
        size_bytes=stat.st_size,
        sha256=sha256,
        sha1=sha1,
    )


def _parse_checksum_file(checksum_file: Path, basename: str) -> tuple[str | None, str | None]:
    resolved = checksum_file.expanduser().resolve()
    if not resolved.is_file():
        msg = f"Checksum file not found: {checksum_file}"
        raise WikipediaPrepareError(msg)
    sha1: str | None = None
    sha256: str | None = None
    for line in resolved.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        digest, filename = parts[0], parts[-1]
        if filename != basename and not filename.endswith(basename):
            continue
        if len(digest) == 40 and re.fullmatch(r"[0-9a-fA-F]+", digest):
            sha1 = digest.lower()
        elif len(digest) == 64 and re.fullmatch(r"[0-9a-fA-F]+", digest):
            sha256 = digest.lower()
    return sha1, sha256


def _verify_checksums(
    fingerprint: InputFingerprint,
    *,
    expected_sha1: str | None,
    expected_sha256: str | None,
) -> None:
    if expected_sha256 and fingerprint.sha256.lower() != expected_sha256.lower():
        msg = (
            f"SHA-256 checksum mismatch for {fingerprint.normalized_path}: "
            f"expected {expected_sha256.lower()}, got {fingerprint.sha256}"
        )
        raise WikipediaPrepareError(msg)
    if expected_sha1 and fingerprint.sha1 and fingerprint.sha1.lower() != expected_sha1.lower():
        msg = (
            f"SHA-1 checksum mismatch for {fingerprint.normalized_path}: "
            f"expected {expected_sha1.lower()}, got {fingerprint.sha1}"
        )
        raise WikipediaPrepareError(msg)
    if expected_sha1 and not fingerprint.sha1:
        msg = "SHA-1 verification requested but SHA-1 was not calculated"
        raise WikipediaPrepareError(msg)


def _nfc_title(title: str) -> str:
    return unicodedata.normalize("NFC", title)


def _wiki_article_url(base_url: str, title: str) -> str:
    normalized_base = base_url if base_url.endswith("/") else base_url + "/"
    wiki_title = title.replace(" ", "_")
    return normalized_base + quote(wiki_title, safe="/:@!$&'()*+,;=-._~")


def build_resume_command(
    *,
    input_path: str,
    output_path: str,
    project: str | None = None,
) -> str:
    parts = [
        "ark corpus prepare-wikipedia",
        f'"{input_path}"',
        f'--output "{output_path}"',
        "--resume",
    ]
    if project:
        parts.insert(3, f"--project {project}")
    return " ".join(parts)


def build_ingest_command(
    *,
    output_path: str,
    index_slug: str,
    batch_size: int = DEFAULT_INGEST_BATCH_SIZE,
) -> str:
    return (
        f"ark corpus ingest \"{output_path}\" "
        f"--index {index_slug} --batch-size {batch_size}"
    )


def prepare_wikipedia_result_to_dict(result: PrepareWikipediaResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "input_path": result.input_path,
        "output_path": result.output_path,
        "project": result.project,
        "status": result.status.value,
        "pages_scanned": result.pages_scanned,
        "records_emitted": result.records_emitted,
        "redirects_skipped": result.redirects_skipped,
        "namespace_pages_skipped": result.namespace_pages_skipped,
        "short_pages_skipped": result.short_pages_skipped,
        "page_errors": result.page_errors,
        "checkpoint_path": str(result.checkpoint_path),
        "resume_command": result.resume_command,
        "ingest_command": result.ingest_command,
        "elapsed_seconds": result.elapsed_seconds,
        "partial": result.partial,
        "message": result.message,
    }
    if result.manifest_path is not None:
        payload["manifest_path"] = str(result.manifest_path)
    if result.attribution_path is not None:
        payload["attribution_path"] = str(result.attribution_path)
    return payload


def dry_run_result_to_dict(result: PrepareWikipediaDryRunResult) -> dict[str, object]:
    return {
        "input_path": result.input_path,
        "output_path": result.output_path,
        "project": result.project,
        "namespace_filters": list(result.namespace_filters),
        "input_fingerprint": result.input_fingerprint.to_dict(),
        "checkpoint_path": str(result.checkpoint_path),
        "partial_output_path": str(result.partial_output_path),
        "manifest_path": str(result.manifest_path),
        "message": result.message,
    }


def _load_checkpoint(path: Path) -> WikipediaCheckpoint:
    if not path.is_file():
        msg = f"Checkpoint not found: {path}"
        raise WikipediaPrepareError(msg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Malformed checkpoint JSON: {path}"
        raise WikipediaPrepareError(msg) from exc
    if data.get("schema_name") != CHECKPOINT_SCHEMA_NAME:
        msg = f"Unexpected checkpoint schema: {data.get('schema_name')!r}"
        raise WikipediaPrepareError(msg)
    if data.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        msg = f"Unsupported checkpoint version: {data.get('schema_version')!r}"
        raise WikipediaPrepareError(msg)
    try:
        return WikipediaCheckpoint(
            schema_name=data["schema_name"],
            schema_version=data["schema_version"],
            input_path=data["input_path"],
            input_size=data["input_size"],
            input_fingerprint=data["input_fingerprint"],
            output_path=data["output_path"],
            project=data["project"],
            base_url=data["base_url"],
            namespace_filters=list(data["namespace_filters"]),
            include_redirects=bool(data["include_redirects"]),
            min_text_chars=int(data["min_text_chars"]),
            normalizer_version=data["normalizer_version"],
            pages_scanned=int(data["pages_scanned"]),
            records_emitted=int(data["records_emitted"]),
            redirects_skipped=int(data["redirects_skipped"]),
            namespace_pages_skipped=int(data["namespace_pages_skipped"]),
            short_pages_skipped=int(data["short_pages_skipped"]),
            page_errors=int(data["page_errors"]),
            partial_output_bytes=int(data["partial_output_bytes"]),
            status=WikipediaPrepareStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"Malformed checkpoint fields: {path}"
        raise WikipediaPrepareError(msg) from exc


def _validate_checkpoint_compatibility(
    checkpoint: WikipediaCheckpoint,
    *,
    input_fp: InputFingerprint,
    output_path: Path,
    options: PrepareWikipediaOptions,
) -> None:
    mismatches: list[str] = []
    if checkpoint.input_path != input_fp.normalized_path:
        mismatches.append("input path")
    if checkpoint.input_size != input_fp.size_bytes:
        mismatches.append("input size")
    if checkpoint.input_fingerprint != input_fp.sha256:
        mismatches.append("input fingerprint")
    if checkpoint.output_path != str(output_path):
        mismatches.append("output path")
    if checkpoint.project != options.project:
        mismatches.append("project")
    if checkpoint.base_url != options.base_url:
        mismatches.append("base URL")
    if sorted(checkpoint.namespace_filters) != sorted(options.namespace_filters):
        mismatches.append("namespace filters")
    if checkpoint.include_redirects != options.include_redirects:
        mismatches.append("redirect policy")
    if checkpoint.min_text_chars != options.min_text_chars:
        mismatches.append("minimum text length")
    if checkpoint.normalizer_version != NORMALIZER_VERSION:
        mismatches.append("normalizer version")
    if mismatches:
        msg = "Incompatible checkpoint: " + ", ".join(mismatches)
        raise WikipediaPrepareError(msg)


def _new_checkpoint(
    *,
    input_fp: InputFingerprint,
    output_path: Path,
    options: PrepareWikipediaOptions,
) -> WikipediaCheckpoint:
    now = utc_now_iso()
    return WikipediaCheckpoint(
        schema_name=CHECKPOINT_SCHEMA_NAME,
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        input_path=input_fp.normalized_path,
        input_size=input_fp.size_bytes,
        input_fingerprint=input_fp.sha256,
        output_path=str(output_path),
        project=options.project,
        base_url=options.base_url,
        namespace_filters=list(options.namespace_filters),
        include_redirects=options.include_redirects,
        min_text_chars=options.min_text_chars,
        normalizer_version=NORMALIZER_VERSION,
        pages_scanned=0,
        records_emitted=0,
        redirects_skipped=0,
        namespace_pages_skipped=0,
        short_pages_skipped=0,
        page_errors=0,
        partial_output_bytes=0,
        status=WikipediaPrepareStatus.running,
        created_at=now,
        updated_at=now,
    )


def _write_checkpoint(path: Path, checkpoint: WikipediaCheckpoint) -> None:
    checkpoint.updated_at = utc_now_iso()
    _write_json_atomic(path, checkpoint.to_dict())


def _repair_partial_output(partial_path: Path) -> int:
    if not partial_path.exists():
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path.write_text("", encoding="utf-8")
        return 0
    data = partial_path.read_bytes()
    if not data:
        return 0
    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        partial_path.write_bytes(b"")
        return 0
    if last_newline != len(data) - 1:
        data = data[: last_newline + 1]
        partial_path.write_bytes(data)
    line_count = 0
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"Corrupt partial JSONL record in {partial_path}: {exc.msg}"
            raise WikipediaPrepareError(msg) from exc
        line_count += 1
    return line_count


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _build_record(
    *,
    page: MediaWikiPage,
    text: str,
    project: str,
    base_url: str,
    dump_filename: str,
    is_redirect: bool,
) -> dict[str, Any]:
    title = _nfc_title(page.title)
    return {
        "id": f"{project}:page:{page.page_id}",
        "title": title,
        "text": text,
        "source": project,
        "url": _wiki_article_url(base_url, title),
        "metadata": {
            "page_id": page.page_id,
            "revision_id": page.revision_id,
            "revision_timestamp": page.revision_timestamp,
            "revision_sha1": page.revision_sha1,
            "namespace": page.namespace,
            "redirect": is_redirect,
            "redirect_target": page.redirect_target,
            "dump_file": dump_filename,
            "normalizer": NORMALIZER_VERSION,
        },
    }


def _write_attribution(
    path: Path,
    *,
    project: str,
    source_url: str | None,
    dump_date: str | None,
    dump_filename: str,
    dump_sha256: str,
    dump_sha1: str | None,
    manifest_path_value: Path,
) -> None:
    license_url = LICENSE_NOTICE_URLS.get(project, LICENSE_NOTICE_URLS["wikipedia"])
    lines = [
        "Ark Pi Wikipedia Corpus Attribution Notice",
        "",
        f"Source project: {project}",
    ]
    if source_url:
        lines.append(f"Source dump URL: {source_url}")
    if dump_date:
        lines.append(f"Dump date: {dump_date}")
    lines.append(f"Dump filename: {dump_filename}")
    lines.append(f"Dump SHA-256: {dump_sha256}")
    if dump_sha1:
        lines.append(f"Dump SHA-1: {dump_sha1}")
    lines.append(f"Preparation manifest: {manifest_path_value}")
    lines.append("")
    lines.append(
        "Article-level titles, URLs, page ids, and revision metadata are preserved "
        "in the prepared JSONL records."
    )
    lines.append("")
    lines.append(
        "Ark Pi software licensing does not relicense Wikipedia or other Wikimedia "
        "content. Redistributed prepared corpora must preserve applicable attribution "
        "and licensing requirements from the source project."
    )
    lines.append(f"Source license information: {license_url}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_manifest(
    *,
    project: str,
    source_url: str | None,
    base_url: str,
    dump_date: str | None,
    dump_filename: str,
    dump_size_bytes: int,
    dump_sha256: str,
    dump_sha1: str | None,
    namespace_filters: tuple[int, ...],
    include_redirects: bool,
    min_text_chars: int,
    pages_scanned: int,
    records_emitted: int,
    redirects_skipped: int,
    namespace_pages_skipped: int,
    short_pages_skipped: int,
    page_errors: int,
    output_filename: str,
    output_size_bytes: int,
    output_sha256: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_name": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": utc_now_iso(),
        "project": project,
        "source_url": source_url,
        "source_base_url": base_url,
        "dump_date": dump_date,
        "dump_filename": dump_filename,
        "dump_size_bytes": dump_size_bytes,
        "dump_sha256": dump_sha256,
        "normalizer_version": NORMALIZER_VERSION,
        "namespace_filters": list(namespace_filters),
        "redirect_policy": "include" if include_redirects else "skip",
        "minimum_text_characters": min_text_chars,
        "pages_scanned": pages_scanned,
        "records_emitted": records_emitted,
        "redirects_skipped": redirects_skipped,
        "namespace_pages_skipped": namespace_pages_skipped,
        "short_pages_skipped": short_pages_skipped,
        "page_errors": page_errors,
        "output_filename": output_filename,
        "output_size_bytes": output_size_bytes,
        "output_sha256": output_sha256,
        "license_notice_url": LICENSE_NOTICE_URLS.get(project, LICENSE_NOTICE_URLS["wikipedia"]),
        "attribution_notice": (
            "Prepared Wikipedia corpus records preserve article provenance. "
            "Redistribution must comply with the source project's licensing terms."
        ),
    }
    if dump_sha1:
        payload["dump_sha1"] = dump_sha1
    return payload


def _handle_page_error(
    exc: Exception,
    *,
    page: MediaWikiPage | None,
    output_path: Path,
    checkpoint: WikipediaCheckpoint,
    continue_on_page_error: bool,
) -> None:
    if not continue_on_page_error:
        if isinstance(exc, WikipediaPrepareError):
            raise exc
        raise WikipediaPrepareError(str(exc)) from exc
    checkpoint.page_errors += 1
    _append_error(
        output_path,
        {
            "page_id": page.page_id if page else None,
            "title": page.title if page else None,
            "error_type": type(exc).__name__,
            "message": str(exc)[:500],
        },
    )


def _resolve_options(options: PrepareWikipediaOptions) -> tuple[Path, Path]:
    input_path = validate_dump_path(options.input_path)
    output_path = validate_output_path(options.output_path, label="output_path")
    if options.checkpoint_every <= 0:
        msg = "checkpoint-every must be greater than 0"
        raise WikipediaPrepareError(msg)
    if options.min_text_chars < 0:
        msg = "min-text-chars must be non-negative"
        raise WikipediaPrepareError(msg)
    if options.limit is not None and options.limit <= 0:
        msg = "limit must be greater than 0"
        raise WikipediaPrepareError(msg)
    return input_path, output_path


def run_prepare_wikipedia_dry_run(options: PrepareWikipediaOptions) -> PrepareWikipediaDryRunResult:
    input_path, output_path = _resolve_options(options)
    need_sha1 = bool(options.expected_sha1 or options.checksum_file)
    input_fp = fingerprint_input(input_path, compute_sha1=need_sha1)
    return PrepareWikipediaDryRunResult(
        input_path=input_fp.normalized_path,
        output_path=str(output_path),
        project=options.project,
        namespace_filters=options.namespace_filters,
        input_fingerprint=input_fp,
        checkpoint_path=checkpoint_path(output_path),
        partial_output_path=partial_output_path(output_path),
        manifest_path=manifest_path(output_path),
        message=(
            "Dry run completed; no output written. Sequential compressed dumps require "
            "a full rescan on resume."
        ),
    )


def run_prepare_wikipedia(
    options: PrepareWikipediaOptions,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> PrepareWikipediaResult:
    started = time.monotonic()
    input_path, output_path = _resolve_options(options)
    ckpt_path = checkpoint_path(output_path)
    partial_path = partial_output_path(output_path)
    final_manifest_path = manifest_path(output_path)
    attr_path = attribution_path(output_path)
    dump_filename = input_path.name

    resume_command = build_resume_command(
        input_path=str(input_path),
        output_path=str(output_path),
        project=options.project,
    )
    ingest_command = build_ingest_command(
        output_path=str(output_path),
        index_slug=options.project,
    )

    if options.dry_run:
        dry = run_prepare_wikipedia_dry_run(options)
        return PrepareWikipediaResult(
            input_path=dry.input_path,
            output_path=dry.output_path,
            project=dry.project,
            status=WikipediaPrepareStatus.planned,
            pages_scanned=0,
            records_emitted=0,
            redirects_skipped=0,
            namespace_pages_skipped=0,
            short_pages_skipped=0,
            page_errors=0,
            checkpoint_path=ckpt_path,
            manifest_path=None,
            attribution_path=None,
            resume_command=resume_command,
            ingest_command=ingest_command,
            elapsed_seconds=time.monotonic() - started,
            message=dry.message,
        )

    if output_path.exists() and not options.force and not options.resume:
        msg = f"Output already exists: {output_path}. Use --force --yes or --resume."
        raise WikipediaPrepareError(msg)

    if options.force:
        if not options.yes:
            msg = "Refusing --force without --yes"
            raise WikipediaPrepareError(msg)
        for sidecar in (
            output_path,
            partial_path,
            ckpt_path,
            errors_path(output_path),
            final_manifest_path,
            manifest_partial_path(output_path),
            attr_path,
        ):
            if sidecar.exists():
                sidecar.unlink()

    _check_disk_space(output_path)

    expected_sha1 = options.expected_sha1
    expected_sha256 = options.expected_sha256
    if options.checksum_file is not None:
        file_sha1, file_sha256 = _parse_checksum_file(options.checksum_file, dump_filename)
        expected_sha1 = expected_sha1 or file_sha1
        expected_sha256 = expected_sha256 or file_sha256

    need_sha1 = bool(expected_sha1)
    if progress_callback:
        progress_callback("Calculating input fingerprint...")
    input_fp = fingerprint_input(input_path, compute_sha1=need_sha1)
    _verify_checksums(input_fp, expected_sha1=expected_sha1, expected_sha256=expected_sha256)

    normalizer = ArkPiWikipediaV1Normalizer()
    namespace_set = set(options.namespace_filters)
    skip_until = 0

    if options.resume:
        checkpoint = _load_checkpoint(ckpt_path)
        _validate_checkpoint_compatibility(
            checkpoint,
            input_fp=input_fp,
            output_path=output_path,
            options=options,
        )
        if checkpoint.status == WikipediaPrepareStatus.completed and output_path.exists():
            return PrepareWikipediaResult(
                input_path=str(input_path),
                output_path=str(output_path),
                project=options.project,
                status=WikipediaPrepareStatus.completed,
                pages_scanned=checkpoint.pages_scanned,
                records_emitted=checkpoint.records_emitted,
                redirects_skipped=checkpoint.redirects_skipped,
                namespace_pages_skipped=checkpoint.namespace_pages_skipped,
                short_pages_skipped=checkpoint.short_pages_skipped,
                page_errors=checkpoint.page_errors,
                checkpoint_path=ckpt_path,
                manifest_path=final_manifest_path if final_manifest_path.exists() else None,
                attribution_path=attr_path if attr_path.exists() else None,
                resume_command=resume_command,
                ingest_command=ingest_command,
                elapsed_seconds=time.monotonic() - started,
                message="Preparation already completed.",
            )
        repaired_records = _repair_partial_output(partial_path)
        if repaired_records != checkpoint.records_emitted:
            msg = (
                f"Partial output record count ({repaired_records}) does not match checkpoint "
                f"records_emitted ({checkpoint.records_emitted})"
            )
            raise WikipediaPrepareError(msg)
        skip_until = checkpoint.pages_scanned
        checkpoint.status = WikipediaPrepareStatus.running
        _write_checkpoint(ckpt_path, checkpoint)
        if progress_callback:
            progress_callback(
                "Resuming preparation. Sequential compressed dumps require a full rescan "
                f"from the beginning; skipping first {skip_until} scanned pages."
            )
    else:
        if ckpt_path.exists() and not options.force:
            msg = (
                f"Existing preparation checkpoint found at {ckpt_path}. "
                "Use --resume to continue or --force --yes to replace."
            )
            raise WikipediaPrepareError(msg)
        checkpoint = _new_checkpoint(
            input_fp=input_fp,
            output_path=output_path,
            options=options,
        )
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        if not partial_path.exists():
            partial_path.write_text("", encoding="utf-8")
        _write_checkpoint(ckpt_path, checkpoint)

    partial = False
    interrupted = False
    file_page_index = 0

    try:
        stream, _compression = open_dump_stream(input_path)
        try:
            with partial_path.open("a", encoding="utf-8") as out_handle:
                for page in iter_mediawiki_pages(stream):
                    file_page_index += 1
                    checkpoint.pages_scanned = file_page_index
                    if file_page_index <= skip_until:
                        if (
                            file_page_index % options.checkpoint_every == 0
                            and progress_callback
                        ):
                            progress_callback(
                                f"Rescanning... pages_scanned={file_page_index}"
                            )
                        continue

                    try:
                        if page.namespace not in namespace_set:
                            checkpoint.namespace_pages_skipped += 1
                            continue

                        is_redirect = page.redirect_target is not None
                        if is_redirect and not options.include_redirects:
                            checkpoint.redirects_skipped += 1
                            continue

                        if is_redirect and options.include_redirects:
                            normalized = redirect_text(page.redirect_target or "")
                            visible_chars = len(re.sub(r"\s+", "", normalized))
                        else:
                            cleaned = normalizer.normalize(page.revision_text)
                            normalized = cleaned.text
                            visible_chars = cleaned.visible_chars

                        if visible_chars < options.min_text_chars:
                            checkpoint.short_pages_skipped += 1
                            continue

                        record = _build_record(
                            page=page,
                            text=normalized,
                            project=options.project,
                            base_url=options.base_url,
                            dump_filename=dump_filename,
                            is_redirect=is_redirect and options.include_redirects,
                        )
                        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        out_handle.write(line + "\n")
                        out_handle.flush()
                        checkpoint.records_emitted += 1
                        checkpoint.partial_output_bytes = partial_path.stat().st_size

                        if options.limit is not None and checkpoint.records_emitted >= options.limit:
                            break

                    except (MediaWikiXmlError, ValueError) as exc:
                        _handle_page_error(
                            exc,
                            page=page,
                            output_path=output_path,
                            checkpoint=checkpoint,
                            continue_on_page_error=options.continue_on_page_error,
                        )
                        partial = partial or options.continue_on_page_error
                        continue
                    except Exception as exc:
                        _handle_page_error(
                            exc,
                            page=page,
                            output_path=output_path,
                            checkpoint=checkpoint,
                            continue_on_page_error=options.continue_on_page_error,
                        )
                        partial = partial or options.continue_on_page_error
                        continue

                    if file_page_index % options.checkpoint_every == 0:
                        _fsync_file(partial_path)
                        _write_checkpoint(ckpt_path, checkpoint)
                        if progress_callback:
                            progress_callback(
                                "Progress: "
                                f"pages_scanned={checkpoint.pages_scanned} "
                                f"records_emitted={checkpoint.records_emitted} "
                                f"redirects_skipped={checkpoint.redirects_skipped} "
                                f"errors={checkpoint.page_errors}"
                            )
        finally:
            stream.close()

        _fsync_file(partial_path)
        partial_path.replace(output_path)
        output_sha256 = sha256_file(output_path)
        manifest_payload = _build_manifest(
            project=options.project,
            source_url=options.source_url,
            base_url=options.base_url,
            dump_date=options.dump_date,
            dump_filename=dump_filename,
            dump_size_bytes=input_fp.size_bytes,
            dump_sha256=input_fp.sha256,
            dump_sha1=input_fp.sha1,
            namespace_filters=options.namespace_filters,
            include_redirects=options.include_redirects,
            min_text_chars=options.min_text_chars,
            pages_scanned=checkpoint.pages_scanned,
            records_emitted=checkpoint.records_emitted,
            redirects_skipped=checkpoint.redirects_skipped,
            namespace_pages_skipped=checkpoint.namespace_pages_skipped,
            short_pages_skipped=checkpoint.short_pages_skipped,
            page_errors=checkpoint.page_errors,
            output_filename=output_path.name,
            output_size_bytes=output_path.stat().st_size,
            output_sha256=output_sha256,
        )
        _write_json_atomic(final_manifest_path, manifest_payload)
        _write_attribution(
            attr_path,
            project=options.project,
            source_url=options.source_url,
            dump_date=options.dump_date,
            dump_filename=dump_filename,
            dump_sha256=input_fp.sha256,
            dump_sha1=input_fp.sha1,
            manifest_path_value=final_manifest_path,
        )
        checkpoint.status = (
            WikipediaPrepareStatus.failed
            if checkpoint.page_errors > 0
            else WikipediaPrepareStatus.completed
        )
        _write_checkpoint(ckpt_path, checkpoint)
        if checkpoint.status == WikipediaPrepareStatus.completed and ckpt_path.exists():
            ckpt_path.unlink()

    except KeyboardInterrupt:
        interrupted = True
        checkpoint.status = WikipediaPrepareStatus.interrupted
        _write_checkpoint(ckpt_path, checkpoint)
        elapsed = time.monotonic() - started
        result = PrepareWikipediaResult(
            input_path=str(input_path),
            output_path=str(output_path),
            project=options.project,
            status=WikipediaPrepareStatus.interrupted,
            pages_scanned=checkpoint.pages_scanned,
            records_emitted=checkpoint.records_emitted,
            redirects_skipped=checkpoint.redirects_skipped,
            namespace_pages_skipped=checkpoint.namespace_pages_skipped,
            short_pages_skipped=checkpoint.short_pages_skipped,
            page_errors=checkpoint.page_errors,
            checkpoint_path=ckpt_path,
            manifest_path=None,
            attribution_path=None,
            resume_command=resume_command,
            ingest_command=ingest_command,
            elapsed_seconds=elapsed,
            partial=True,
            message=(
                f"Interrupted. Sequential compressed dumps require a rescan on resume. "
                f"Resume with: {resume_command}"
            ),
        )
        raise WikipediaPrepareInterrupted(result) from None

    elapsed = time.monotonic() - started
    final_status = checkpoint.status
    if checkpoint.page_errors > 0:
        partial = True

    if progress_callback:
        rate = checkpoint.pages_scanned / elapsed if elapsed > 0 else 0.0
        progress_callback(
            f"Completed: pages_scanned={checkpoint.pages_scanned} "
            f"records_emitted={checkpoint.records_emitted} "
            f"elapsed={elapsed:.1f}s rate={rate:.1f} pages/s"
        )
        progress_callback(f"Ingest with: {ingest_command}")

    return PrepareWikipediaResult(
        input_path=str(input_path),
        output_path=str(output_path),
        project=options.project,
        status=final_status,
        pages_scanned=checkpoint.pages_scanned,
        records_emitted=checkpoint.records_emitted,
        redirects_skipped=checkpoint.redirects_skipped,
        namespace_pages_skipped=checkpoint.namespace_pages_skipped,
        short_pages_skipped=checkpoint.short_pages_skipped,
        page_errors=checkpoint.page_errors,
        checkpoint_path=ckpt_path,
        manifest_path=final_manifest_path if output_path.exists() else None,
        attribution_path=attr_path if attr_path.exists() else None,
        resume_command=resume_command,
        ingest_command=ingest_command,
        elapsed_seconds=elapsed,
        partial=partial or interrupted,
        message="Wikipedia preparation completed."
        if final_status == WikipediaPrepareStatus.completed
        else "Wikipedia preparation finished with page errors.",
    )
