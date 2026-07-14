import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ark_pi.config import ArkSettings, clear_settings_cache
from ark_pi.embeddings import (
    EmbeddingBackendUnavailable,
    EmbeddingDependencyMissing,
    EmbeddingDimensionMismatch,
    EmbeddingInvalidVector,
    EmbeddingModelMissing,
    EmbeddingNetworkDisabled,
    clear_embedder_cache,
    create_embedder,
    embeddings_passive_status,
    run_embeddings_active_test,
)
from ark_pi.embeddings.factory import create_embedder as factory_create_embedder
from ark_pi.embeddings.mock import MOCK_DIMENSIONS, MockEmbedder
from ark_pi.embeddings.math_util import assert_vectors_finite, cosine_similarity
from ark_pi.embeddings.validation import validate_embedding_settings


@pytest.fixture(autouse=True)
def reset_embedder_cache() -> None:
    clear_embedder_cache()
    clear_settings_cache()


def test_mock_embedder_returns_deterministic_vectors() -> None:
    embedder = MockEmbedder(model_name="test-model", normalize=False)
    first = embedder.embed_documents(["alpha", "beta"])
    second = embedder.embed_documents(["alpha", "beta"])

    assert first == second
    assert first[0] != first[1]


def test_mock_vector_count_matches_input_count() -> None:
    embedder = MockEmbedder(model_name="test-model", normalize=False)
    vectors = embedder.embed_documents(["one", "two", "three"])
    assert len(vectors) == 3


def test_mock_empty_batch_returns_empty_list() -> None:
    embedder = MockEmbedder(model_name="test-model", normalize=False)
    assert embedder.embed_documents([]) == []


def test_mock_rejects_empty_text() -> None:
    embedder = MockEmbedder(model_name="test-model", normalize=False)
    with pytest.raises(EmbeddingInvalidVector, match="Empty text"):
        embedder.embed_documents([""])


def test_dimension_mismatch_raises_typed_error() -> None:
    with pytest.raises(EmbeddingDimensionMismatch):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_non_finite_vector_raises_typed_error() -> None:
    with pytest.raises(EmbeddingInvalidVector, match="non-finite"):
        assert_vectors_finite([[1.0, math.nan]])


def test_unknown_backend_fails_clearly() -> None:
    settings = SimpleNamespace(
        embedding_backend="unknown",
        embedding_device="cpu",
        embedding_batch_size=16,
        embedding_dimensions=384,
        embedding_model_path=None,
    )

    with pytest.raises(EmbeddingBackendUnavailable, match="Unknown embedding backend"):
        validate_embedding_settings(settings)  # type: ignore[arg-type]


def test_missing_local_model_path_fails_before_load(tmp_path: Path) -> None:
    missing = tmp_path / "missing-model"
    settings = ArkSettings(
        embedding_backend="sentence-transformers",
        embedding_model_path=missing,
    )

    with pytest.raises(EmbeddingModelMissing, match="does not exist"):
        create_embedder(settings)


def test_network_disabled_configuration_blocks_remote_resolution() -> None:
    settings = ArkSettings(
        embedding_backend="sentence-transformers",
        embedding_model_path=None,
        embedding_allow_network=False,
    )

    with pytest.raises(EmbeddingNetworkDisabled):
        create_embedder(settings).embed_documents(["hello"])


def test_missing_optional_dependency_fails_clearly(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    settings = ArkSettings(
        embedding_backend="sentence-transformers",
        embedding_model_path=model_dir,
        embedding_allow_network=True,
    )

    with patch(
        "ark_pi.embeddings.sentence_transformers.SentenceTransformersEmbedder._resolved_local_path",
        return_value=None,
    ):
        with pytest.raises(EmbeddingDependencyMissing, match="sentence-transformers"):
            create_embedder(settings).embed_documents(["hello"])


def test_passive_status_performs_no_model_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    with patch("ark_pi.embeddings.factory.create_embedder") as create:
        status = embeddings_passive_status()

    create.assert_not_called()
    assert status.model_load_performed is False
    assert status.network_check_performed is False


def test_active_test_returns_structured_dimensions_and_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_active_test()

    assert result.ok is True
    assert result.dimensions == MOCK_DIMENSIONS
    assert result.texts_embedded == 3
    assert result.load_ms >= 0
    assert result.embedding_ms >= 0
    assert result.vectors_finite is True


def test_active_test_calculates_cosine_similarities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_active_test()

    assert isinstance(result.related_similarity, float)
    assert isinstance(result.unrelated_similarity, float)


def test_active_test_detects_related_fixture_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()

    result = run_embeddings_active_test()
    assert result.related_ranks_higher is True


def test_model_instance_is_reused_within_one_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARK_EMBEDDING_BACKEND", "mock")
    clear_settings_cache()
    settings = ArkSettings()

    first = factory_create_embedder(settings)
    second = factory_create_embedder(settings)

    assert first is second


def test_sentence_transformers_backend_with_fake_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    class FakeRow:
        def __init__(self, values: list[float]) -> None:
            self._values = values

        def tolist(self) -> list[float]:
            return self._values

    class FakeEncoded:
        def __init__(self, values: list[list[float]]) -> None:
            self._rows = [FakeRow(row) for row in values]

        def __iter__(self):
            return iter(self._rows)

    class FakeModel:
        def encode(
            self,
            texts: list[str],
            *,
            batch_size: int,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> FakeEncoded:
            del batch_size, convert_to_numpy, normalize_embeddings, show_progress_bar
            return FakeEncoded([[0.1, 0.2, 0.3] for _ in texts])

        def get_sentence_embedding_dimension(self) -> int:
            return 3

    class FakeSentenceTransformer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._model = FakeModel()

        def encode(self, *args: object, **kwargs: object) -> FakeEncoded:
            return self._model.encode(*args, **kwargs)

        def get_sentence_embedding_dimension(self) -> int:
            return self._model.get_sentence_embedding_dimension()

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    fake_torch = types.ModuleType("torch")

    class _NoGrad:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_args: object) -> None:
            return None

    fake_torch.no_grad = _NoGrad
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    settings = ArkSettings(
        embedding_backend="sentence-transformers",
        embedding_model_path=model_dir,
        embedding_dimensions=3,
    )
    embedder = create_embedder(settings)
    vectors = embedder.embed_documents(["alpha", "beta"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 3
