import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ark_pi.embeddings.math_util import assert_vectors_finite
from ark_pi.embeddings.mock import MOCK_DIMENSIONS
from ark_pi.rag.index import (
    MANIFEST_FILE,
    ChunkDocument,
    IndexErrorBase,
    IndexFormatError,
    IndexStats,
)

if TYPE_CHECKING:
    from ark_pi.config import ArkSettings
    from ark_pi.embeddings.types import Embedder

FINGERPRINT_VERSION = 1
SEMANTIC_SCHEMA_VERSION = 2
CHUNK_SCHEMA_VERSION = 1


class SemanticIndexError(IndexErrorBase):
    """Base class for semantic index failures."""


class SemanticIndexCompatibilityError(SemanticIndexError):
    """Embedding identity does not match the existing semantic index."""


class SemanticIndexDuplicateConflictError(SemanticIndexError):
    """A document ID already exists with different content."""


@dataclass(frozen=True)
class EmbeddingIdentity:
    backend: str
    model_name: str
    dimensions: int
    normalizes_vectors: bool
    model_path_id: str | None = None
    fingerprint_version: int = FINGERPRINT_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "fingerprint_version": self.fingerprint_version,
            "backend": self.backend,
            "model_name": self.model_name,
            "dimensions": self.dimensions,
            "normalizes_vectors": self.normalizes_vectors,
        }
        if self.model_path_id is not None:
            payload["model_path_id"] = self.model_path_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmbeddingIdentity":
        return cls(
            backend=str(data["backend"]),
            model_name=str(data["model_name"]),
            dimensions=int(data["dimensions"]),
            normalizes_vectors=bool(data["normalizes_vectors"]),
            model_path_id=str(data["model_path_id"]) if data.get("model_path_id") else None,
            fingerprint_version=int(data.get("fingerprint_version", FINGERPRINT_VERSION)),
        )


def model_path_id_from_path(model_path: Path | None) -> str | None:
    if model_path is None:
        return None
    resolved = model_path.expanduser()
    return resolved.name or None


def identity_from_embedder(
    embedder: "Embedder",
    settings: "ArkSettings",
) -> EmbeddingIdentity:
    return EmbeddingIdentity(
        backend=embedder.backend_name,
        model_name=embedder.model_name,
        dimensions=embedder.dimensions,
        normalizes_vectors=embedder.normalizes_vectors,
        model_path_id=model_path_id_from_path(settings.embedding_model_path),
    )


def identity_from_settings(
    settings: "ArkSettings",
    *,
    embedding_backend: str | None = None,
    model_path: Path | None = None,
) -> EmbeddingIdentity:
    backend = embedding_backend or settings.embedding_backend
    resolved_path = model_path if model_path is not None else settings.embedding_model_path
    if backend == "mock":
        dimensions = MOCK_DIMENSIONS
    else:
        dimensions = settings.embedding_dimensions
    return EmbeddingIdentity(
        backend=backend,
        model_name=settings.embedding_model,
        dimensions=dimensions,
        normalizes_vectors=settings.embedding_normalize,
        model_path_id=model_path_id_from_path(resolved_path),
    )


def compute_embedding_fingerprint(identity: EmbeddingIdentity) -> str:
    payload = identity.to_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def identity_from_manifest(manifest: dict[str, object]) -> EmbeddingIdentity | None:
    embedding_raw = manifest.get("embedding")
    if not isinstance(embedding_raw, dict):
        return None
    try:
        identity = EmbeddingIdentity.from_dict(embedding_raw)
    except (KeyError, TypeError, ValueError):
        msg = "Invalid embedding metadata in index manifest"
        raise IndexFormatError(msg) from None
    return identity


def validate_embedding_compatibility(
    existing: EmbeddingIdentity,
    requested: EmbeddingIdentity,
) -> None:
    if existing.backend != requested.backend:
        msg = (
            f"Embedding backend mismatch: index has {existing.backend!r}, "
            f"configured {requested.backend!r}. Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)
    if existing.model_name != requested.model_name:
        msg = (
            f"Embedding model mismatch: index has {existing.model_name!r}, "
            f"configured {requested.model_name!r}. Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)
    if existing.model_path_id != requested.model_path_id:
        msg = (
            "Embedding model path identity mismatch. "
            "Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)
    if existing.dimensions != requested.dimensions:
        msg = (
            f"Embedding dimension mismatch: index has {existing.dimensions}, "
            f"configured {requested.dimensions}. Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)
    if existing.normalizes_vectors != requested.normalizes_vectors:
        msg = (
            "Embedding normalization setting mismatch. "
            "Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)
    existing_fp = compute_embedding_fingerprint(existing)
    requested_fp = compute_embedding_fingerprint(requested)
    if existing_fp != requested_fp:
        msg = (
            "Embedding fingerprint mismatch. "
            "Rebuild the index with --force-rebuild."
        )
        raise SemanticIndexCompatibilityError(msg)


def embed_and_validate(
    embedder: "Embedder",
    texts: Sequence[str],
    *,
    batch_size: int,
) -> list[list[float]]:
    if batch_size <= 0:
        msg = "embedding batch size must be greater than 0"
        raise ValueError(msg)
    if not texts:
        return []
    all_vectors: list[list[float]] = []
    expected_dimensions = embedder.dimensions
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        vectors = embedder.embed_documents(batch)
        assert_vectors_finite(vectors, expected_dimensions=expected_dimensions)
        all_vectors.extend(vectors)
    return all_vectors


def _chunk_records_to_documents(
    records: list[dict[str, object]],
) -> list[ChunkDocument]:
    documents: list[ChunkDocument] = []
    for data in records:
        documents.append(
            ChunkDocument(
                id=str(data["id"]),
                title=str(data["title"]),
                source=str(data["source"]),
                chunk_index=int(data["chunk_index"]),
                text=str(data["text"]),
                sha256=str(data["sha256"]),
            )
        )
    return documents


def append_semantic_batch(
    chunk_records: list[dict[str, object]],
    index_dir: Path,
    *,
    backend: str,
    source_chunks: str,
    embedder: "Embedder",
    embedding_identity: EmbeddingIdentity,
    collection_name: str,
    embedding_batch_size: int,
) -> IndexStats:
    documents = _chunk_records_to_documents(chunk_records)
    if not documents:
        return _empty_stats(index_dir, backend, source_chunks)

    texts = [document.text for document in documents]
    embeddings = embed_and_validate(embedder, texts, batch_size=embedding_batch_size)

    match backend:
        case "chroma":
            from ark_pi.rag import chroma_index

            return chroma_index.append_documents(
                documents,
                index_dir,
                embeddings=embeddings,
                source_chunks=source_chunks,
                embedding_identity=embedding_identity,
                collection_name=collection_name,
            )
        case _:
            msg = f"Unsupported semantic index backend: {backend!r}"
            raise SemanticIndexError(msg)


def _empty_stats(index_dir: Path, backend: str, source_chunks: str) -> IndexStats:
    manifest_path = index_dir / MANIFEST_FILE
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(manifest, dict):
            return IndexStats(
                backend=backend,
                schema_version=int(manifest.get("schema_version", SEMANTIC_SCHEMA_VERSION)),
                chunk_count=int(manifest.get("chunk_count", 0)),
                index_dir=index_dir,
                source_chunks=str(manifest.get("source_chunks", source_chunks)),
            )
    return IndexStats(
        backend=backend,
        schema_version=SEMANTIC_SCHEMA_VERSION,
        chunk_count=0,
        index_dir=index_dir,
        source_chunks=source_chunks,
    )
