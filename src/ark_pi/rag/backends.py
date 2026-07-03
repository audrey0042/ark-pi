from typing import Literal

IndexBackendName = Literal["simple", "chroma"]

SUPPORTED_BACKENDS: frozenset[str] = frozenset({"simple", "chroma"})
DEFAULT_COLLECTION_NAME = "ark_chunks"

CHROMA_INSTALL_HINT = (
    "Chroma backend requires optional dependency: "
    "pip install -e '.[chroma]' or pip install -e '.[dev,chroma]'."
)


def validate_backend_name(name: str) -> IndexBackendName:
    if name not in SUPPORTED_BACKENDS:
        from ark_pi.rag.index import IndexConfigurationError

        msg = f"Unsupported index backend: {name!r} (allowed: {', '.join(sorted(SUPPORTED_BACKENDS))})"
        raise IndexConfigurationError(msg)
    return name  # type: ignore[return-value]


def resolve_build_backend(*, cli_backend: str | None, config_backend: str) -> IndexBackendName:
    if cli_backend is not None:
        return validate_backend_name(cli_backend)
    return validate_backend_name(config_backend)


def resolve_query_backend(
    *,
    cli_backend: str | None,
    manifest_backend: str,
) -> IndexBackendName:
    from ark_pi.rag.index import IndexConfigurationError

    manifest = validate_backend_name(manifest_backend)
    if cli_backend is None:
        return manifest
    requested = validate_backend_name(cli_backend)
    if requested != manifest:
        msg = (
            f"Requested backend {requested!r} does not match "
            f"index manifest backend {manifest!r}"
        )
        raise IndexConfigurationError(msg)
    return requested
