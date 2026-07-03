import hashlib
import json
import re
from pathlib import Path

from ark_pi.ingest.sources import SourceRecord

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        msg = "chunk-size must be greater than 0"
        raise ValueError(msg)
    if chunk_overlap < 0:
        msg = "chunk-overlap must be greater than or equal to 0"
        raise ValueError(msg)
    if chunk_overlap >= chunk_size:
        msg = "chunk-overlap must be smaller than chunk-size"
        raise ValueError(msg)


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    validate_chunk_params(chunk_size, chunk_overlap)
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[str] = []
    step = chunk_size - chunk_overlap
    start = 0
    while start < len(stripped):
        chunk = stripped[start : start + chunk_size]
        chunks.append(chunk)
        if start + chunk_size >= len(stripped):
            break
        start += step
    return chunks


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_to_slug(source: str) -> str:
    basename = Path(source).name
    stem = Path(basename).stem if "." in basename else basename
    slug = _SLUG_RE.sub("_", stem.lower()).strip("_")
    return slug or "source"


def make_chunk_id(source_slug: str, chunk_index: int, text: str) -> str:
    content_hash = sha256_hex(text)[:12]
    return f"{source_slug}:{chunk_index:06d}:{content_hash}"


def make_chunk_records(
    sources: list[SourceRecord],
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, object]]:
    validate_chunk_params(chunk_size, chunk_overlap)
    records: list[dict[str, object]] = []
    for source in sources:
        slug = source_to_slug(source.source)
        for chunk_index, chunk_text in enumerate(
            split_text(source.text, chunk_size, chunk_overlap)
        ):
            records.append(
                {
                    "id": make_chunk_id(slug, chunk_index, chunk_text),
                    "title": source.title,
                    "source": source.source,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                    "sha256": sha256_hex(chunk_text),
                }
            )
    return records


def write_chunks_jsonl(
    records: list[dict[str, object]],
    output_path: Path,
    *,
    force: bool,
) -> None:
    if output_path.exists() and not force:
        msg = f"Output file already exists: {output_path} (use --force to overwrite)"
        raise FileExistsError(msg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
