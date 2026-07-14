class EmbeddingError(Exception):
    """Base class for embedding runtime failures that CLI may catch."""


class EmbeddingBackendUnavailable(EmbeddingError):
    """Unsupported or misconfigured embedding backend."""


class EmbeddingDependencyMissing(EmbeddingError):
    """Optional ML dependencies are not installed."""


class EmbeddingModelMissing(EmbeddingError):
    """Configured local model path is missing or invalid."""


class EmbeddingModelLoadFailed(EmbeddingError):
    """Model could not be loaded from the resolved path or identifier."""


class EmbeddingNetworkDisabled(EmbeddingError):
    """Remote model resolution is disabled and no local model path is configured."""


class EmbeddingDimensionMismatch(EmbeddingError):
    """Model output dimensions do not match the configured expectation."""


class EmbeddingInvalidVector(EmbeddingError):
    """Vector contains non-finite values or invalid input text."""


class EmbeddingBatchFailed(EmbeddingError):
    """Embedding inference failed for a batch of texts."""
