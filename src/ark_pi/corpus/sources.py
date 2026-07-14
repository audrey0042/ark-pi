import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ark_pi.corpus.fingerprint import sha256_hex
from ark_pi.corpus.types import CorpusDocument, CorpusSourceFormat
from ark_pi.ingest.chunking import sha256_hex as chunk_sha256_hex


def _slugify_document_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_:" else "_" for ch in value.strip())
    return cleaned or "document"


def derive_document_id(*, source_key: str, text: str, supplied_id: str | None) -> str:
    if supplied_id is not None and supplied_id.strip():
        return _slugify_document_id(supplied_id.strip())
    digest = chunk_sha256_hex(f"{source_key}\n{text}")[:16]
    return f"doc-{digest}"


def _normalize_text_field(data: dict[str, Any]) -> str:
    if "text" in data:
        return str(data["text"]).strip()
    if "content" in data:
        return str(data["content"]).strip()
    msg = "Missing required field 'text' (or alias 'content')"
    raise ValueError(msg)


def _metadata_from_record(data: dict[str, Any]) -> dict[str, Any] | None:
    metadata: dict[str, Any] = {}
    for key in ("url", "metadata"):
        if key in data:
            metadata[key] = data[key]
    if "source" in data:
        metadata["record_source"] = data["source"]
    return metadata or None


def iter_jsonl_documents(path: Path) -> Iterator[CorpusDocument]:
    resolved = path.expanduser().resolve()
    position = 0
    with resolved.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                msg = f"Malformed JSON on line {line_number} of {resolved}: {exc.msg}"
                raise ValueError(msg) from exc
            if not isinstance(data, dict):
                msg = f"Expected JSON object on line {line_number} of {resolved}"
                raise ValueError(msg)

            text = _normalize_text_field(data)
            if not text:
                continue

            title = str(data.get("title", f"line-{line_number}"))
            record_source = str(data.get("source", f"{resolved}:{line_number}"))
            source_key = f"{resolved}:{line_number}:{record_source}"
            supplied_id = str(data["id"]) if "id" in data and data["id"] is not None else None
            document_id = derive_document_id(
                source_key=source_key,
                text=text,
                supplied_id=supplied_id,
            )
            content_digest = sha256_hex(text)
            metadata = _metadata_from_record(data)

            yield CorpusDocument(
                document_id=document_id,
                title=title,
                text=text,
                source=record_source,
                content_digest=content_digest,
                position=position,
                metadata=metadata,
            )
            position += 1


def _iter_txt_files(root: Path) -> list[Path]:
    files: list[Path] = []
    resolved_root = root.expanduser().resolve()
    for path in sorted(resolved_root.rglob("*.txt")):
        if not path.is_file():
            continue
        if path.is_symlink():
            resolved = path.resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError as exc:
                msg = f"Symlink escapes source root: {path}"
                raise ValueError(msg) from exc
            path = resolved
        files.append(path)
    return files


def iter_text_directory_documents(root: Path) -> Iterator[CorpusDocument]:
    resolved_root = root.expanduser().resolve()
    txt_files = _iter_txt_files(resolved_root)
    if not txt_files:
        msg = f"No .txt files found under directory: {root}"
        raise ValueError(msg)

    position = 0
    for txt_file in txt_files:
        relative = txt_file.relative_to(resolved_root).as_posix()
        try:
            text = txt_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            msg = f"Unreadable file: {txt_file}"
            raise ValueError(msg) from exc
        if not text:
            continue

        source_key = f"{resolved_root}:{relative}"
        document_id = derive_document_id(source_key=source_key, text=text, supplied_id=None)
        content_digest = sha256_hex(text)
        title = Path(relative).stem

        yield CorpusDocument(
            document_id=document_id,
            title=title,
            text=text,
            source=relative,
            content_digest=content_digest,
            position=position,
            metadata={"relative_path": relative},
        )
        position += 1


def iter_corpus_documents(path: Path, source_format: CorpusSourceFormat) -> Iterator[CorpusDocument]:
    if source_format == CorpusSourceFormat.jsonl:
        yield from iter_jsonl_documents(path)
        return
    yield from iter_text_directory_documents(path)


def estimate_record_count(path: Path, source_format: CorpusSourceFormat) -> int | None:
    if source_format == CorpusSourceFormat.text_directory:
        try:
            return len(_iter_txt_files(path))
        except ValueError:
            return None

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        return None
    count = 0
    with resolved.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            try:
                text = _normalize_text_field(data)
            except ValueError:
                continue
            if text:
                count += 1
    return count
