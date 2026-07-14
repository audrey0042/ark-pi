from pathlib import Path
from typing import TYPE_CHECKING

from ark_pi.embeddings.errors import EmbeddingBackendUnavailable
from ark_pi.embeddings.mock import MockEmbedder
from ark_pi.embeddings.types import Embedder
from ark_pi.embeddings.validation import validate_embedding_settings

if TYPE_CHECKING:
    from ark_pi.config import ArkSettings

_CACHE: dict[tuple[object, ...], Embedder] = {}


def clear_embedder_cache() -> None:
    _CACHE.clear()


def create_embedder(
    settings: "ArkSettings",
    *,
    allow_network_override: bool | None = None,
    model_path_override: Path | None = None,
) -> Embedder:
    validate_embedding_settings(settings)

    allow_network = (
        settings.embedding_allow_network
        if allow_network_override is None
        else allow_network_override
    )
    model_path = (
        settings.embedding_model_path
        if model_path_override is None
        else model_path_override
    )

    cache_key = (
        settings.embedding_backend,
        str(model_path),
        settings.embedding_model,
        settings.embedding_device,
        settings.embedding_normalize,
        settings.embedding_dimensions,
        settings.embedding_batch_size,
        allow_network,
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    backend = settings.embedding_backend
    if backend == "mock":
        embedder: Embedder = MockEmbedder(
            model_name=settings.embedding_model,
            normalize=settings.embedding_normalize,
        )
    elif backend == "sentence-transformers":
        from ark_pi.embeddings.sentence_transformers import SentenceTransformersEmbedder

        embedder = SentenceTransformersEmbedder(
            model_name=settings.embedding_model,
            model_path=model_path,
            batch_size=settings.embedding_batch_size,
            normalize=settings.embedding_normalize,
            device=settings.embedding_device,
            expected_dimensions=settings.embedding_dimensions,
            allow_network=allow_network,
        )
    else:
        msg = f"Unsupported embedding backend: {backend!r}"
        raise EmbeddingBackendUnavailable(msg)

    _CACHE[cache_key] = embedder
    return embedder
