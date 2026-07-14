import math

from ark_pi.embeddings.errors import EmbeddingDimensionMismatch, EmbeddingInvalidVector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        msg = f"Vector dimension mismatch: {len(a)} vs {len(b)}"
        raise EmbeddingDimensionMismatch(msg)
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for left, right in zip(a, b, strict=True):
        dot += left * right
        norm_a += left * left
        norm_b += right * right
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def assert_vectors_finite(
    vectors: list[list[float]],
    *,
    expected_dimensions: int | None = None,
) -> None:
    if not vectors:
        return
    first_dim = len(vectors[0])
    for index, vector in enumerate(vectors):
        if len(vector) != first_dim:
            msg = (
                f"Vector at index {index} has dimension {len(vector)}, "
                f"expected {first_dim}"
            )
            raise EmbeddingDimensionMismatch(msg)
        if expected_dimensions is not None and expected_dimensions > 0:
            if len(vector) != expected_dimensions:
                msg = (
                    f"Vector at index {index} has dimension {len(vector)}, "
                    f"expected {expected_dimensions}"
                )
                raise EmbeddingDimensionMismatch(msg)
        for value in vector:
            if not math.isfinite(value):
                msg = f"Vector at index {index} contains non-finite value: {value!r}"
                raise EmbeddingInvalidVector(msg)
