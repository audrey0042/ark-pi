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
from ark_pi.rag.semantic_index import (
    CHUNK_SCHEMA_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    EmbeddingIdentity,
    SemanticIndexDuplicateConflictError,
    compute_embedding_fingerprint,
    identity_from_manifest,
    validate_embedding_compatibility,
)
from ark_pi.workspace.catalog import utc_now_iso

BACKEND_NAME = "chroma"
LEGACY_SCHEMA_VERSION = 1
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


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _embedding_block(
    identity: EmbeddingIdentity,
    *,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, object]:
    now = utc_now_iso()
    block: dict[str, object] = {
        **identity.to_dict(),
        "fingerprint": compute_embedding_fingerprint(identity),
        "created_at": created_at or now,
        "updated_at": updated_at or now,
    }
    return block


def _write_semantic_manifest(
    index_dir: Path,
    *,
    chunk_count: int,
    source_chunks: str,
    collection_name: str,
    embedding_identity: EmbeddingIdentity,
    created_at: str | None = None,
) -> None:
    now = utc_now_iso()
    manifest_path = index_dir / MANIFEST_FILE
    embedding_created = created_at or now
    payload: dict[str, object] = {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "backend": BACKEND_NAME,
        "created_by": CREATED_BY,
        "chunk_count": chunk_count,
        "collection_name": collection_name,
        "source_chunks": source_chunks,
        "embedding": _embedding_block(
            embedding_identity,
            created_at=embedding_created,
            updated_at=now,
        ),
        "corpus": {
            "preparation_schema_version": None,
            "chunk_schema_version": CHUNK_SCHEMA_VERSION,
        },
    }
    _write_json_atomic(manifest_path, payload)


def _update_semantic_manifest(
    index_dir: Path,
    *,
    chunk_count: int,
    source_chunks: str,
) -> None:
    manifest = _load_manifest(index_dir)
    embedding_raw = manifest.get("embedding")
    if not isinstance(embedding_raw, dict):
        msg = "Chroma semantic index manifest is missing embedding metadata"
        raise IndexFormatError(msg)
    embedding_raw["updated_at"] = utc_now_iso()
    manifest["chunk_count"] = chunk_count
    manifest["source_chunks"] = source_chunks
    manifest["embedding"] = embedding_raw
    _write_json_atomic(index_dir / MANIFEST_FILE, manifest)


def _write_legacy_manifest(
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
                "schema_version": LEGACY_SCHEMA_VERSION,
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


def _get_or_create_collection(
    client: Any,
    *,
    collection_name: str,
    embedding_identity: EmbeddingIdentity,
):
    try:
        return client.get_collection(collection_name)
    except (ValueError, Exception):
        return client.create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine" if embedding_identity.normalizes_vectors else "l2",
            },
        )


def _resolve_existing_records(
    collection: Any,
    documents: list[ChunkDocument],
) -> tuple[list[ChunkDocument], list[list[float]], int]:
    if not documents:
        return [], [], 0

    ids = [document.id for document in documents]
    try:
        existing = collection.get(ids=ids, include=["metadatas"])
    except Exception:
        return documents, list(range(len(documents))), 0

    existing_ids = set(existing.get("ids") or [])
    existing_metas = existing.get("metadatas") or []
    meta_by_id = {
        doc_id: meta
        for doc_id, meta in zip(existing.get("ids") or [], existing_metas, strict=False)
        if meta is not None
    }

    to_add: list[ChunkDocument] = []
    embedding_indices: list[int] = []
    skipped = 0
    for index, document in enumerate(documents):
        if document.id not in existing_ids:
            to_add.append(document)
            embedding_indices.append(index)
            continue
        metadata = meta_by_id.get(document.id, {})
        existing_sha = str(metadata.get("sha256", ""))
        if existing_sha == document.sha256:
            skipped += 1
            continue
        msg = (
            f"Document ID {document.id!r} already exists with different content. "
            "Use --force-rebuild --yes to rebuild the index."
        )
        raise SemanticIndexDuplicateConflictError(msg)

    return to_add, embedding_indices, skipped


def append_documents(
    documents: list[ChunkDocument],
    index_dir: Path,
    *,
    embeddings: list[list[float]],
    source_chunks: str,
    embedding_identity: EmbeddingIdentity,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> IndexStats:
    if len(embeddings) != len(documents):
        msg = (
            f"Embedding count ({len(embeddings)}) does not match "
            f"document count ({len(documents)})"
        )
        raise IndexConfigurationError(msg)

    chromadb = _import_chromadb()
    index_dir.mkdir(parents=True, exist_ok=True)

    if _index_dir_nonempty(index_dir):
        manifest = _load_manifest(index_dir)
        existing_identity = identity_from_manifest(manifest)
        if existing_identity is None:
            msg = (
                "Existing Chroma index lacks semantic embedding metadata. "
                "Use --force-rebuild --yes to rebuild as a semantic index."
            )
            raise IndexFormatError(msg)
        validate_embedding_compatibility(existing_identity, embedding_identity)
        resolved_collection = _collection_name_from_manifest(manifest)
    else:
        resolved_collection = collection_name

    client = chromadb.PersistentClient(path=str(index_dir))
    collection = _get_or_create_collection(
        client,
        collection_name=resolved_collection,
        embedding_identity=embedding_identity,
    )

    to_add, embedding_indices, _skipped = _resolve_existing_records(collection, documents)
    if not to_add and _index_dir_nonempty(index_dir):
        manifest = _load_manifest(index_dir)
        return IndexStats(
            backend=BACKEND_NAME,
            schema_version=int(manifest.get("schema_version", SEMANTIC_SCHEMA_VERSION)),
            chunk_count=int(manifest.get("chunk_count", 0)),
            index_dir=index_dir,
            source_chunks=str(manifest.get("source_chunks", source_chunks)),
        )

    if to_add:
        add_embeddings = [embeddings[index] for index in embedding_indices]
        ids = [document.id for document in to_add]
        texts = [document.text for document in to_add]
        metadatas = [
            {
                "title": document.title,
                "source": document.source,
                "chunk_index": document.chunk_index,
                "sha256": document.sha256,
            }
            for document in to_add
        ]
        collection.add(
            ids=ids,
            embeddings=add_embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    if _index_dir_nonempty(index_dir) and (index_dir / MANIFEST_FILE).is_file():
        manifest = _load_manifest(index_dir)
        chunk_count = int(manifest.get("chunk_count", 0)) + len(to_add)
        _update_semantic_manifest(
            index_dir,
            chunk_count=chunk_count,
            source_chunks=source_chunks,
        )
    else:
        _write_semantic_manifest(
            index_dir,
            chunk_count=len(to_add),
            source_chunks=source_chunks,
            collection_name=resolved_collection,
            embedding_identity=embedding_identity,
        )

    manifest = _load_manifest(index_dir)
    return IndexStats(
        backend=BACKEND_NAME,
        schema_version=int(manifest.get("schema_version", SEMANTIC_SCHEMA_VERSION)),
        chunk_count=int(manifest["chunk_count"]),
        index_dir=index_dir,
        source_chunks=str(manifest.get("source_chunks", source_chunks)),
    )


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
                "Use corpus ingest with --backend chroma and a configured embedder."
            )
            raise IndexConfigurationError(msg) from exc

    _write_legacy_manifest(
        index_dir,
        chunk_count=len(documents),
        source_chunks=source_chunks,
        collection_name=collection_name,
    )

    return IndexStats(
        backend=BACKEND_NAME,
        schema_version=LEGACY_SCHEMA_VERSION,
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
            "Semantic query execution is deferred to a future slice."
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


def read_semantic_metadata(index_dir: Path) -> dict[str, object] | None:
    if not (index_dir / MANIFEST_FILE).is_file():
        return None
    manifest = _load_manifest(index_dir)
    embedding_raw = manifest.get("embedding")
    if not isinstance(embedding_raw, dict):
        return None
    return dict(embedding_raw)
