import json
import re
import shutil
from collections import Counter
from pathlib import Path

from ark_pi.rag.index import CREATED_BY, ChunkDocument, IndexStats, SearchResult

BACKEND_NAME = "simple"
SCHEMA_VERSION = 1
DOCUMENTS_FILE = "documents.jsonl"
TERMS_FILE = "terms.json"
MANIFEST_FILE = "manifest.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _term_frequencies(text: str) -> dict[str, int]:
    return dict(Counter(tokenize(text)))


def _write_json(path: Path, data: object) -> None:
    path.write_text(
        json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _index_dir_nonempty(index_dir: Path) -> bool:
    if not index_dir.exists():
        return False
    return any(index_dir.iterdir())


def _prepare_index_dir(index_dir: Path, *, force: bool) -> None:
    if _index_dir_nonempty(index_dir) and not force:
        msg = f"Index directory is not empty: {index_dir} (use --force to overwrite)"
        raise FileExistsError(msg)
    if index_dir.exists() and force:
        shutil.rmtree(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)


def _document_to_dict(document: ChunkDocument) -> dict[str, object]:
    return {
        "id": document.id,
        "title": document.title,
        "source": document.source,
        "chunk_index": document.chunk_index,
        "text": document.text,
        "sha256": document.sha256,
    }


def _document_from_dict(data: dict[str, object]) -> ChunkDocument:
    return ChunkDocument(
        id=str(data["id"]),
        title=str(data["title"]),
        source=str(data["source"]),
        chunk_index=int(data["chunk_index"]),
        text=str(data["text"]),
        sha256=str(data["sha256"]),
    )


def build_index(
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    source_chunks: str,
    force: bool = False,
) -> IndexStats:
    _prepare_index_dir(index_dir, force=force)

    documents_path = index_dir / DOCUMENTS_FILE
    terms_path = index_dir / TERMS_FILE
    manifest_path = index_dir / MANIFEST_FILE

    terms: dict[str, dict[str, int]] = {}
    lines: list[str] = []
    for document in documents:
        lines.append(json.dumps(_document_to_dict(document), ensure_ascii=False))
        terms[document.id] = _term_frequencies(document.text)

    documents_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    _write_json(terms_path, terms)
    _write_json(
        manifest_path,
        {
            "schema_version": SCHEMA_VERSION,
            "backend": BACKEND_NAME,
            "created_by": CREATED_BY,
            "chunk_count": len(documents),
            "source_chunks": source_chunks,
        },
    )

    return IndexStats(
        backend=BACKEND_NAME,
        schema_version=SCHEMA_VERSION,
        chunk_count=len(documents),
        index_dir=index_dir,
        source_chunks=source_chunks,
    )


def _load_documents(index_dir: Path) -> list[ChunkDocument]:
    documents_path = index_dir / DOCUMENTS_FILE
    if not documents_path.is_file():
        msg = f"Invalid index directory (missing {DOCUMENTS_FILE}): {index_dir}"
        raise ValueError(msg)
    documents: list[ChunkDocument] = []
    for line in documents_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        data = json.loads(stripped)
        if not isinstance(data, dict):
            msg = f"Invalid document record in {documents_path}"
            raise ValueError(msg)
        documents.append(_document_from_dict(data))
    return documents


def _load_terms(index_dir: Path) -> dict[str, dict[str, int]]:
    terms_path = index_dir / TERMS_FILE
    if not terms_path.is_file():
        msg = f"Invalid index directory (missing {TERMS_FILE}): {index_dir}"
        raise ValueError(msg)
    data = json.loads(terms_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Invalid terms file in {terms_path}"
        raise ValueError(msg)
    return {str(doc_id): {str(token): int(count) for token, count in terms.items()} for doc_id, terms in data.items()}


def _score_document(query_tokens: list[str], term_counts: dict[str, int]) -> float:
    score = 0.0
    for token in query_tokens:
        frequency = term_counts.get(token, 0)
        if frequency > 0:
            score += 1.0 + (0.1 * frequency)
    return score


def search_index(index_dir: Path, query: str, *, limit: int) -> list[SearchResult]:
    documents = _load_documents(index_dir)
    terms = _load_terms(index_dir)
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, ChunkDocument]] = []
    for document in documents:
        doc_terms = terms.get(document.id, {})
        score = _score_document(query_tokens, doc_terms)
        if score > 0:
            scored.append((score, document))

    scored.sort(key=lambda item: (-item[0], item[1].id))

    results: list[SearchResult] = []
    for score, document in scored[:limit]:
        results.append(
            SearchResult(
                score=score,
                id=document.id,
                title=document.title,
                source=document.source,
                chunk_index=document.chunk_index,
                text=document.text,
            )
        )
    return results
