import importlib.util
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ark_pi.embeddings.factory import create_embedder
from ark_pi.embeddings.fixtures import BUILTIN_EVALUATION_FIXTURE, DEFAULT_ACTIVE_TEST_TEXTS
from ark_pi.embeddings.math_util import assert_vectors_finite, cosine_similarity
from ark_pi.embeddings.types import (
    EmbeddingsActiveTestResult,
    EmbeddingsEvaluateResult,
    EmbeddingsPassiveStatus,
)

if TYPE_CHECKING:
    from ark_pi.config import ArkSettings


def _model_path_display(path: Path | None) -> str:
    if path is None:
        return ""
    text = str(path).strip()
    if not text or text == ".":
        return ""
    return text


def _model_path_exists(path: Path | None) -> bool:
    resolved = _model_path_display(path)
    if not resolved:
        return False
    return path.is_dir() if path is not None else False


def _dependency_importable() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def _passive_message(
    *,
    backend: str,
    model_path: str,
    model_path_exists: bool,
    dependency_importable: bool,
) -> str:
    if backend == "mock":
        if dependency_importable:
            return (
                "Mock embedding backend is configured. "
                "Passive status does not load a model or contact the network."
            )
        return (
            "Mock embedding backend is configured. Optional sentence-transformers "
            "dependencies are not importable, which is fine for mock mode. "
            "Passive status does not load a model or contact the network."
        )
    if backend == "sentence-transformers":
        if not dependency_importable:
            return (
                "Sentence-transformers backend is configured but optional dependencies "
                "are not importable. Install with: pip install -e '.[embeddings]'"
            )
        if model_path and not model_path_exists:
            return (
                f"Sentence-transformers backend is configured for local path {model_path!r}, "
                "but the path does not exist. Passive status does not load a model."
            )
        return (
            "Sentence-transformers backend is configured. "
            "Use an explicit embedding test to load the model and run inference."
        )
    return f"Configured embedding backend: {backend!r}."


def embeddings_passive_status(
    settings: "ArkSettings | None" = None,
) -> EmbeddingsPassiveStatus:
    """Return configured embedding settings without loading a model or contacting the network."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    model_path = _model_path_display(settings.embedding_model_path)
    path_exists = _model_path_exists(settings.embedding_model_path)
    dependency_importable = _dependency_importable()

    return EmbeddingsPassiveStatus(
        backend=settings.embedding_backend,
        model=settings.embedding_model,
        model_path=model_path,
        model_path_exists=path_exists,
        expected_dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        normalize=settings.embedding_normalize,
        device=settings.embedding_device,
        allow_network=settings.embedding_allow_network,
        dependency_importable=dependency_importable,
        model_load_performed=False,
        network_check_performed=False,
        message=_passive_message(
            backend=settings.embedding_backend,
            model_path=model_path,
            model_path_exists=path_exists,
            dependency_importable=dependency_importable,
        ),
    )


def run_embeddings_active_test(
    *,
    texts: list[str] | None = None,
    settings: "ArkSettings | None" = None,
    allow_network: bool | None = None,
    model_path: Path | None = None,
) -> EmbeddingsActiveTestResult:
    """Load the configured embedder and run a diagnostic embedding test."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    fixture_texts = list(texts if texts is not None else DEFAULT_ACTIVE_TEST_TEXTS)
    if not fixture_texts:
        fixture_texts = list(DEFAULT_ACTIVE_TEST_TEXTS)

    load_started = time.perf_counter()
    embedder = create_embedder(
        settings,
        allow_network_override=allow_network,
        model_path_override=model_path,
    )
    load_ms = int((time.perf_counter() - load_started) * 1000)

    embed_started = time.perf_counter()
    vectors = embedder.embed_documents(fixture_texts)
    embedding_ms = int((time.perf_counter() - embed_started) * 1000)

    expected_dims = settings.embedding_dimensions
    if embedder.backend_name == "mock":
        expected_dims = embedder.dimensions
    assert_vectors_finite(vectors, expected_dimensions=expected_dims or None)

    status = embedder.status()
    resolved_model_path = status.get("resolved_model_path")
    if isinstance(resolved_model_path, str):
        resolved_path: str | None = resolved_model_path
    else:
        resolved_path = None

    related_similarity = cosine_similarity(vectors[0], vectors[1])
    unrelated_similarity = cosine_similarity(vectors[0], vectors[2])
    related_ranks_higher = related_similarity > unrelated_similarity

    return EmbeddingsActiveTestResult(
        ok=True,
        backend=embedder.backend_name,
        model=embedder.model_name,
        resolved_model_path=resolved_path,
        dimensions=embedder.dimensions,
        batch_size=settings.embedding_batch_size,
        normalize=settings.embedding_normalize,
        load_ms=load_ms,
        embedding_ms=embedding_ms,
        texts_embedded=len(fixture_texts),
        vectors_finite=True,
        related_similarity=related_similarity,
        unrelated_similarity=unrelated_similarity,
        related_ranks_higher=related_ranks_higher,
        message=(
            "Embedding diagnostic test succeeded. "
            "Related-water similarity ranking is a heuristic only, not a quality certification."
        ),
    )


def passive_status_to_dict(status: EmbeddingsPassiveStatus) -> dict[str, object]:
    return {
        "backend": status.backend,
        "model": status.model,
        "model_path": status.model_path,
        "model_path_exists": status.model_path_exists,
        "expected_dimensions": status.expected_dimensions,
        "batch_size": status.batch_size,
        "normalize": status.normalize,
        "device": status.device,
        "allow_network": status.allow_network,
        "dependency_importable": status.dependency_importable,
        "model_load_performed": status.model_load_performed,
        "network_check_performed": status.network_check_performed,
        "message": status.message,
    }


def active_test_to_dict(result: EmbeddingsActiveTestResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "backend": result.backend,
        "model": result.model,
        "resolved_model_path": result.resolved_model_path,
        "dimensions": result.dimensions,
        "batch_size": result.batch_size,
        "normalize": result.normalize,
        "load_ms": result.load_ms,
        "embedding_ms": result.embedding_ms,
        "texts_embedded": result.texts_embedded,
        "vectors_finite": result.vectors_finite,
        "related_similarity": result.related_similarity,
        "unrelated_similarity": result.unrelated_similarity,
        "related_ranks_higher": result.related_ranks_higher,
        "message": result.message,
    }


def load_evaluation_fixture(path: Path | None) -> dict[str, Any]:
    if path is None:
        return dict(BUILTIN_EVALUATION_FIXTURE)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read evaluation fixture {path}: {exc}"
        raise ValueError(msg) from exc
    data = json.loads(content)
    if not isinstance(data, dict):
        msg = "Evaluation fixture must be a JSON object"
        raise ValueError(msg)
    return data


def _validate_fixture(data: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    records = data.get("records")
    queries = data.get("queries")
    if not isinstance(records, list) or not isinstance(queries, list):
        msg = "Evaluation fixture must include 'records' and 'queries' arrays"
        raise ValueError(msg)

    parsed_records: list[dict[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            msg = "Each record must be an object with id and text"
            raise ValueError(msg)
        record_id = record.get("id")
        text = record.get("text")
        if not isinstance(record_id, str) or not isinstance(text, str):
            msg = "Each record must include string id and text fields"
            raise ValueError(msg)
        parsed_records.append({"id": record_id, "text": text})

    parsed_queries: list[dict[str, object]] = []
    for query in queries:
        if not isinstance(query, dict):
            msg = "Each query must be an object with query and relevant_ids"
            raise ValueError(msg)
        query_text = query.get("query")
        relevant_ids = query.get("relevant_ids")
        if not isinstance(query_text, str):
            msg = "Each query must include a string query field"
            raise ValueError(msg)
        if not isinstance(relevant_ids, list) or not all(
            isinstance(item, str) for item in relevant_ids
        ):
            msg = "Each query must include relevant_ids as a string array"
            raise ValueError(msg)
        parsed_queries.append({"query": query_text, "relevant_ids": relevant_ids})

    return parsed_records, parsed_queries


def _rank_documents(
    query_vector: list[float],
    records: list[dict[str, str]],
    doc_vectors: list[list[float]],
) -> list[str]:
    scored = [
        (cosine_similarity(query_vector, vector), record["id"])
        for record, vector in zip(records, doc_vectors, strict=True)
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [record_id for _, record_id in scored]


def run_embeddings_evaluate(
    *,
    settings: "ArkSettings | None" = None,
    fixture_path: Path | None = None,
    allow_network: bool | None = None,
    model_path: Path | None = None,
) -> EmbeddingsEvaluateResult:
    """Run offline retrieval-quality evaluation without creating or modifying indexes."""
    if settings is None:
        from ark_pi.config import get_settings

        settings = get_settings()

    fixture = load_evaluation_fixture(fixture_path)
    records, queries = _validate_fixture(fixture)

    started = time.perf_counter()
    embedder = create_embedder(
        settings,
        allow_network_override=allow_network,
        model_path_override=model_path,
    )

    doc_vectors = embedder.embed_documents([record["text"] for record in records])
    query_vectors = embedder.embed_documents([str(item["query"]) for item in queries])
    total_latency_ms = int((time.perf_counter() - started) * 1000)

    top1_hits = 0
    recall_at_3_total = 0.0
    mrr_total = 0.0

    for query_item, query_vector in zip(queries, query_vectors, strict=True):
        ranked_ids = _rank_documents(query_vector, records, doc_vectors)
        relevant_ids = list(query_item["relevant_ids"])
        relevant_set = set(relevant_ids)

        if ranked_ids and ranked_ids[0] in relevant_set:
            top1_hits += 1

        top3 = ranked_ids[:3]
        recall_at_3_total += len(relevant_set.intersection(top3)) / len(relevant_set)

        reciprocal_rank = 0.0
        for rank, record_id in enumerate(ranked_ids, start=1):
            if record_id in relevant_set:
                reciprocal_rank = 1.0 / rank
                break
        mrr_total += reciprocal_rank

    query_count = len(queries)
    status = embedder.status()
    resolved_model_path = status.get("resolved_model_path")
    resolved_path = resolved_model_path if isinstance(resolved_model_path, str) else None

    return EmbeddingsEvaluateResult(
        ok=True,
        backend=embedder.backend_name,
        model=embedder.model_name,
        resolved_model_path=resolved_path,
        dimensions=embedder.dimensions,
        top1_accuracy=top1_hits / query_count if query_count else 0.0,
        recall_at_3=recall_at_3_total / query_count if query_count else 0.0,
        mean_reciprocal_rank=mrr_total / query_count if query_count else 0.0,
        query_count=query_count,
        documents_count=len(records),
        total_latency_ms=total_latency_ms,
        message="Offline embedding evaluation completed.",
    )


def evaluate_result_to_dict(result: EmbeddingsEvaluateResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "backend": result.backend,
        "model": result.model,
        "resolved_model_path": result.resolved_model_path,
        "dimensions": result.dimensions,
        "top1_accuracy": result.top1_accuracy,
        "recall_at_3": result.recall_at_3,
        "mean_reciprocal_rank": result.mean_reciprocal_rank,
        "query_count": result.query_count,
        "documents_count": result.documents_count,
        "total_latency_ms": result.total_latency_ms,
        "message": result.message,
    }
