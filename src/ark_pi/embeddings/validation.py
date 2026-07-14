from pathlib import Path
from typing import TYPE_CHECKING

from ark_pi.embeddings.errors import (
    EmbeddingBackendUnavailable,
    EmbeddingModelMissing,
)

if TYPE_CHECKING:
    from ark_pi.config import ArkSettings

SUPPORTED_BACKENDS = frozenset({"mock", "sentence-transformers"})
SUPPORTED_DEVICES = frozenset({"cpu"})


def validate_embedding_settings(settings: "ArkSettings") -> None:
    if settings.embedding_backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        msg = (
            f"Unknown embedding backend {settings.embedding_backend!r}. "
            f"Supported backends: {supported}"
        )
        raise EmbeddingBackendUnavailable(msg)

    if settings.embedding_device not in SUPPORTED_DEVICES:
        supported = ", ".join(sorted(SUPPORTED_DEVICES))
        msg = (
            f"Unsupported embedding device {settings.embedding_device!r}. "
            f"Supported devices: {supported}"
        )
        raise EmbeddingBackendUnavailable(msg)

    if settings.embedding_batch_size <= 0:
        msg = "embedding_batch_size must be greater than zero"
        raise EmbeddingBackendUnavailable(msg)

    if settings.embedding_dimensions < 0:
        msg = "embedding_dimensions must be zero or greater"
        raise EmbeddingBackendUnavailable(msg)

    model_path = _resolved_model_path(settings.embedding_model_path)
    if model_path is not None:
        if not model_path.exists():
            msg = f"Configured embedding model path does not exist: {model_path}"
            raise EmbeddingModelMissing(msg)
        if not model_path.is_dir():
            msg = f"Configured embedding model path is not a directory: {model_path}"
            raise EmbeddingModelMissing(msg)


def _resolved_model_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text or text == ".":
        return None
    return path
