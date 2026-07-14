import hashlib
import math
import re
import struct
from collections.abc import Sequence
from typing import Any

from ark_pi.embeddings.errors import EmbeddingInvalidVector
from ark_pi.embeddings.math_util import assert_vectors_finite

MOCK_DIMENSIONS = 8
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "how",
        "in",
        "making",
        "methods",
        "of",
        "safe",
        "the",
        "to",
    }
)
_WATER_HINTS = frozenset({"water", "drinkable", "drinking", "purify", "purification"})
_BICYCLE_HINTS = frozenset({"bicycle", "chain", "repair", "gear", "derailleur"})


class MockEmbedder:
    """Deterministic mock embedder for offline tests. Not semantically meaningful."""

    def __init__(self, *, model_name: str, normalize: bool) -> None:
        self._model_name = model_name
        self._normalize = normalize

    @property
    def backend_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return MOCK_DIMENSIONS

    @property
    def normalizes_vectors(self) -> bool:
        return self._normalize

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [self._vector_for_text(text) for text in texts]
        assert_vectors_finite(vectors, expected_dimensions=MOCK_DIMENSIONS)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "dimensions": self.dimensions,
            "normalize": self.normalizes_vectors,
            "resolved_model_path": None,
            "message": (
                "Mock embedding backend is configured. "
                "Vectors are deterministic but not semantically meaningful."
            ),
        }

    def _vector_for_text(self, text: str) -> list[float]:
        if not text:
            msg = "Empty text cannot be embedded"
            raise EmbeddingInvalidVector(msg)
        tokens = [
            token
            for token in _TOKEN_PATTERN.findall(text.lower())
            if token not in _STOPWORDS
        ]
        if not tokens:
            tokens = [text.lower()]
        values = [0.0] * MOCK_DIMENSIONS
        for token in tokens:
            token_vector = self._token_vector(token)
            for index, value in enumerate(token_vector):
                values[index] += value
        count = float(len(tokens))
        values = [value / count for value in values]
        if tokens and any(token in _WATER_HINTS for token in tokens):
            for index in range(4):
                values[index] += 3.0
        if tokens and any(token in _BICYCLE_HINTS for token in tokens):
            for index in range(4, MOCK_DIMENSIONS):
                values[index] += 3.0
        if self._normalize:
            values = self._l2_normalize(values)
        return values

    def _token_vector(self, token: str) -> list[float]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        values: list[float] = []
        for offset in range(0, MOCK_DIMENSIONS * 4, 4):
            chunk = digest[offset : offset + 4]
            if len(chunk) < 4:
                chunk = chunk + digest[: 4 - len(chunk)]
            raw = struct.unpack(">I", chunk)[0]
            values.append((raw / 2**32) * 2.0 - 1.0)
        return values

    @staticmethod
    def _l2_normalize(values: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            return values
        return [value / norm for value in values]
