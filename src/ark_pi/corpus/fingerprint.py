import hashlib
import json
from pathlib import Path
from typing import BinaryIO

from ark_pi.corpus.types import CorpusSourceFormat, SourceFingerprint

_HASH_BLOCK_SIZE = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    return hash_file(path, algorithm="sha256")


def sha1_file(path: Path) -> str:
    return hash_file(path, algorithm="sha1")


def hash_file(path: Path, *, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while True:
            block = handle.read(_HASH_BLOCK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def hash_stream(handle: BinaryIO, *, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    while True:
        block = handle.read(_HASH_BLOCK_SIZE)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_source_format(path: Path) -> CorpusSourceFormat:
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        return CorpusSourceFormat.text_directory
    if resolved.suffix == ".jsonl":
        return CorpusSourceFormat.jsonl
    msg = f"Unsupported corpus source format: {path} (expected .jsonl or directory of .txt files)"
    raise ValueError(msg)


def _iter_txt_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.txt")):
        if not path.is_file():
            continue
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError as exc:
                msg = f"Symlink escapes source root: {path}"
                raise ValueError(msg) from exc
            path = resolved
        files.append(path)
    return files


def fingerprint_jsonl(path: Path) -> SourceFingerprint:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        msg = f"JSONL source does not exist: {path}"
        raise FileNotFoundError(msg)
    stat = resolved.stat()
    return SourceFingerprint(
        format=CorpusSourceFormat.jsonl,
        normalized_path=str(resolved),
        fingerprint=sha256_file(resolved),
        file_count=1,
        total_bytes=stat.st_size,
        mtime=stat.st_mtime,
    )


def fingerprint_text_directory(root: Path) -> SourceFingerprint:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        msg = f"Text directory source does not exist: {root}"
        raise FileNotFoundError(msg)

    txt_files = _iter_txt_files(resolved)
    if not txt_files:
        msg = f"No .txt files found under directory: {root}"
        raise ValueError(msg)

    entries: list[dict[str, object]] = []
    total_bytes = 0
    for txt_file in txt_files:
        relative = txt_file.relative_to(resolved).as_posix()
        try:
            stat = txt_file.stat()
            content_hash = sha256_file(txt_file)
        except OSError as exc:
            msg = f"Unreadable file: {txt_file}"
            raise ValueError(msg) from exc
        total_bytes += stat.st_size
        entries.append(
            {
                "relative_path": relative,
                "size": stat.st_size,
                "content_hash": content_hash,
            }
        )

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return SourceFingerprint(
        format=CorpusSourceFormat.text_directory,
        normalized_path=str(resolved),
        fingerprint=digest,
        file_count=len(entries),
        total_bytes=total_bytes,
    )


def fingerprint_source(path: Path) -> SourceFingerprint:
    source_format = detect_source_format(path)
    if source_format == CorpusSourceFormat.jsonl:
        return fingerprint_jsonl(path)
    return fingerprint_text_directory(path)


def derive_run_id(
    *,
    source_fingerprint: SourceFingerprint,
    index_slug: str,
    chunk_size: int,
    chunk_overlap: int,
    backend: str,
) -> str:
    payload = {
        "source_fingerprint": source_fingerprint.fingerprint,
        "source_path": source_fingerprint.normalized_path,
        "index_slug": index_slug,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "backend": backend,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
