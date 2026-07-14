from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

from ark_pi.embeddings.errors import (
    EmbeddingDependencyMissing,
    EmbeddingModelLoadFailed,
    EmbeddingNetworkDisabled,
)
from ark_pi.embeddings.math_util import assert_vectors_finite

EMBEDDINGS_INSTALL_HINT = "Install optional embedding dependencies: pip install -e '.[embeddings]'"


class SentenceTransformersEmbedder:
    """Lazy sentence-transformers backend for local embedding inference."""

    def __init__(
        self,
        *,
        model_name: str,
        model_path: Path | None,
        batch_size: int,
        normalize: bool,
        device: str,
        expected_dimensions: int,
        allow_network: bool,
    ) -> None:
        self._model_name = model_name
        self._model_path = model_path
        self._batch_size = batch_size
        self._normalize = normalize
        self._device = device
        self._expected_dimensions = expected_dimensions
        self._allow_network = allow_network
        self._model: Any = None
        self._resolved_model_path: str | None = None
        self._actual_dimensions: int | None = None

    @property
    def backend_name(self) -> str:
        return "sentence-transformers"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        self._ensure_loaded()
        return self._actual_dimensions or 0

    @property
    def normalizes_vectors(self) -> bool:
        return self._normalize

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        model = self._model
        assert model is not None

        try:
            import torch
        except ImportError as exc:
            msg = f"PyTorch is required for sentence-transformers. {EMBEDDINGS_INSTALL_HINT}"
            raise EmbeddingDependencyMissing(msg) from exc

        try:
            with torch.no_grad():
                encoded = model.encode(
                    list(texts),
                    batch_size=self._batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=self._normalize,
                    show_progress_bar=False,
                )
        except Exception as exc:
            msg = f"Embedding batch failed: {exc}"
            from ark_pi.embeddings.errors import EmbeddingBatchFailed

            raise EmbeddingBatchFailed(msg) from exc

        vectors = [row.tolist() for row in encoded]
        assert_vectors_finite(
            vectors,
            expected_dimensions=self._expected_dimensions or None,
        )
        if self._actual_dimensions is None and vectors:
            self._actual_dimensions = len(vectors[0])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]

    def status(self) -> dict[str, Any]:
        self._ensure_loaded()
        versions: dict[str, str] = {}
        for package in ("sentence-transformers", "torch", "transformers"):
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                continue
        return {
            "backend": self.backend_name,
            "model": self._model_name,
            "dimensions": self.dimensions,
            "normalize": self._normalize,
            "resolved_model_path": self._resolved_model_path,
            "package_versions": versions,
            "message": "Sentence-transformers embedder is loaded.",
        }

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self._model = self._load_model()

    def _load_model(self) -> Any:
        local_path = self._resolved_local_path()
        if local_path is None and not self._allow_network:
            msg = (
                "Remote model resolution is disabled. Set ARK_EMBEDDING_MODEL_PATH "
                "to a local model directory or enable ARK_EMBEDDING_ALLOW_NETWORK."
            )
            raise EmbeddingNetworkDisabled(msg)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            msg = (
                f"sentence-transformers is not installed. {EMBEDDINGS_INSTALL_HINT}"
            )
            raise EmbeddingDependencyMissing(msg) from exc

        if local_path is not None:
            try:
                model = SentenceTransformer(
                    str(local_path),
                    device=self._device,
                    local_files_only=True,
                )
            except Exception as exc:
                msg = f"Failed to load embedding model from {local_path}: {exc}"
                raise EmbeddingModelLoadFailed(msg) from exc
            self._resolved_model_path = str(local_path)
            self._actual_dimensions = self._infer_dimensions(model)
            return model

        try:
            model = SentenceTransformer(self._model_name, device=self._device)
        except Exception as exc:
            msg = f"Failed to load embedding model {self._model_name!r}: {exc}"
            raise EmbeddingModelLoadFailed(msg) from exc
        self._resolved_model_path = self._model_name
        self._actual_dimensions = self._infer_dimensions(model)
        return model

    def _resolved_local_path(self) -> Path | None:
        if self._model_path is None:
            return None
        text = str(self._model_path).strip()
        if not text or text == ".":
            return None
        return self._model_path

    @staticmethod
    def _infer_dimensions(model: Any) -> int:
        dim = getattr(model, "get_sentence_embedding_dimension", None)
        if callable(dim):
            value = dim()
            if isinstance(value, int):
                return value
        return 0
