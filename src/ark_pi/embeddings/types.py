from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class Embedder(Protocol):
    @property
    def backend_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    @property
    def dimensions(self) -> int:
        ...

    @property
    def normalizes_vectors(self) -> bool:
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def status(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class EmbeddingsPassiveStatus:
    backend: str
    model: str
    model_path: str
    model_path_exists: bool
    expected_dimensions: int
    batch_size: int
    normalize: bool
    device: str
    allow_network: bool
    dependency_importable: bool
    model_load_performed: bool
    network_check_performed: bool
    message: str


@dataclass(frozen=True)
class EmbeddingsActiveTestResult:
    ok: bool
    backend: str
    model: str
    resolved_model_path: str | None
    dimensions: int
    batch_size: int
    normalize: bool
    load_ms: int
    embedding_ms: int
    texts_embedded: int
    vectors_finite: bool
    related_similarity: float
    unrelated_similarity: float
    related_ranks_higher: bool
    message: str


@dataclass(frozen=True)
class EmbeddingsEvaluateResult:
    ok: bool
    backend: str
    model: str
    resolved_model_path: str | None
    dimensions: int
    top1_accuracy: float
    recall_at_3: float
    mean_reciprocal_rank: float
    query_count: int
    documents_count: int
    total_latency_ms: int
    message: str
