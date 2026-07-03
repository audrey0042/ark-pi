import json
import shutil
from pathlib import Path
from typing import Any

from ark_pi.rag.backends import CHROMA_INSTALL_HINT, DEFAULT_COLLECTION_NAME
from ark_pi.rag.index import (
    MANIFEST_FILE,
    ChunkDocument,
    IndexConfigurationError,
    IndexDependencyError,
    IndexFormatError,
    IndexStats,
    SearchResult,
)

BACKEND_NAME = "chroma"
SCHEMA_VERSION = 1
CREATED_BY = "ark-pi"


def _import_chromadb() -> Any:
    try:
        import chromadb
    except ImportError as exc:
        raise IndexDependencyError(CHROMA_INSTALL_HINT) from exc
    return chromadb


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


def _write_manifest(
    index_dir: Path,
    *,
    chunk_count: int,
    source_chunks: str,
    collection_name: str,
) -> None:
    manifest_path = index_dir / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "backend": BACKEND_NAME,
                "created_by": CREATED_BY,
                "chunk_count": chunk_count,
                "collection_name": collection_name,
                "source_chunks": source_chunks,
            },
            sort_keys=True,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_manifest(index_dir: Path) -> dict[str, object]:
    manifest_path = index_dir / MANIFEST_FILE
    if not index_dir.exists():
        msg = f"Index directory does not exist: {index_dir}"
        raise FileNotFoundError(msg)
    if not manifest_path.is_file():
        msg = f"Invalid index directory (missing {MANIFEST_FILE}): {index_dir}"
        raise IndexFormatError(msg)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"Invalid manifest in {manifest_path}"
        raise IndexFormatError(msg)
    if data.get("backend") != BACKEND_NAME:
        msg = f"Expected Chroma index manifest in {index_dir}"
        raise IndexFormatError(msg)
    return data


def _collection_name_from_manifest(manifest: dict[str, object]) -> str:
    name = manifest.get("collection_name")
    if isinstance(name, str) and name:
        return name
    return DEFAULT_COLLECTION_NAME


def build_index(
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    source_chunks: str,
    force: bool = False,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> IndexStats:
    chromadb = _import_chromadb()
    _prepare_index_dir(index_dir, force=force)

    client = chromadb.PersistentClient(path=str(index_dir))
    try:
        client.delete_collection(collection_name)
    except (ValueError, Exception):
        pass

    collection = client.create_collection(name=collection_name)

    if documents:
        ids = [document.id for document in documents]
        texts = [document.text for document in documents]
        metadatas = [
            {
                "title": document.title,
                "source": document.source,
                "chunk_index": document.chunk_index,
                "sha256": document.sha256,
            }
            for document in documents
        ]
        try:
            collection.add(ids=ids, documents=texts, metadatas=metadatas)
        except Exception as exc:
            msg = (
                "Chroma could not index documents with the available embedding setup. "
                "Semantic embedding model selection is a future slice."
            )
            raise IndexConfigurationError(msg) from exc

    _write_manifest(
        index_dir,
        chunk_count=len(documents),
        source_chunks=source_chunks,
        collection_name=collection_name,
    )

    return IndexStats(
        backend=BACKEND_NAME,
        schema_version=SCHEMA_VERSION,
        chunk_count=len(documents),
        index_dir=index_dir,
        source_chunks=source_chunks,
    )


def search_index(index_dir: Path, query: str, *, limit: int) -> list[SearchResult]:
    chromadb = _import_chromadb()
    manifest = _load_manifest(index_dir)
    collection_name = _collection_name_from_manifest(manifest)

    client = chromadb.PersistentClient(path=str(index_dir))
    try:
        collection = client.get_collection(collection_name)
    except ValueError as exc:
        msg = f"Chroma collection not found in index: {collection_name}"
        raise IndexFormatError(msg) from exc

    try:
        raw = collection.query(
            query_texts=[query],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        msg = (
            "Chroma could not query documents with the available embedding setup. "
            "Semantic embedding model selection is a future slice."
        )
        raise IndexConfigurationError(msg) from exc

    ids = raw.get("ids", [[]])[0]
    documents = raw.get("documents", [[]])[0]
    metadatas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0]

    results: list[SearchResult] = []
    for doc_id, text, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
        if text is None or metadata is None:
            continue
        title = str(metadata.get("title", ""))
        source = str(metadata.get("source", ""))
        chunk_index = int(metadata.get("chunk_index", 0))
        score = float(distance) if distance is not None else 0.0
        results.append(
            SearchResult(
                score=score,
                id=str(doc_id),
                title=title,
                source=source,
                chunk_index=chunk_index,
                text=str(text),
            )
        )
    return results
