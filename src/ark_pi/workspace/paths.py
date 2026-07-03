import re
from pathlib import Path

_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_-]+")


def slugify_index_name(name: str) -> str:
    stripped = name.strip().lower()
    if not stripped:
        msg = "index name must not be empty"
        raise ValueError(msg)
    collapsed = re.sub(r"\s+", "-", stripped)
    cleaned = _SLUG_INVALID_CHARS_RE.sub("", collapsed)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_")
    if not cleaned:
        msg = "index name produced an empty slug"
        raise ValueError(msg)
    return cleaned


def validate_index_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        msg = "index name must not be empty"
        raise ValueError(msg)
    if ".." in stripped or "/" in stripped or "\\" in stripped:
        msg = f"invalid index name: {name!r}"
        raise ValueError(msg)
    return slugify_index_name(stripped)


def validate_slug(slug: str) -> str:
    stripped = slug.strip()
    if not stripped:
        msg = "slug must not be empty"
        raise ValueError(msg)
    if ".." in stripped or "/" in stripped or "\\" in stripped:
        msg = f"invalid slug: {slug!r}"
        raise ValueError(msg)
    normalized = slugify_index_name(stripped)
    if normalized != stripped:
        msg = f"invalid slug: {slug!r}"
        raise ValueError(msg)
    return stripped


def resolve_workspace_dir(workspace_dir: Path) -> Path:
    return workspace_dir.expanduser().resolve()


def index_paths(workspace_dir: Path, slug: str) -> tuple[Path, Path]:
    index_root = index_root_dir(workspace_dir, slug)
    chunks_path = index_root / "chunks.jsonl"
    index_dir = index_root / "index"
    ensure_path_inside_workspace(resolve_workspace_dir(workspace_dir), chunks_path)
    ensure_path_inside_workspace(resolve_workspace_dir(workspace_dir), index_dir)
    return chunks_path, index_dir


def index_root_dir(workspace_dir: Path, slug: str) -> Path:
    validated_slug = validate_slug(slug)
    root = resolve_workspace_dir(workspace_dir)
    index_root = (root / "indexes" / validated_slug).resolve()
    ensure_path_inside_workspace(root, index_root)
    if index_root == root:
        msg = "cannot delete workspace root"
        raise ValueError(msg)
    indexes_root = (root / "indexes").resolve()
    try:
        index_root.relative_to(indexes_root)
    except ValueError as exc:
        msg = f"path escapes indexes directory: {index_root}"
        raise ValueError(msg) from exc
    return index_root


def ensure_path_inside_workspace(workspace_dir: Path, path: Path) -> Path:
    root = resolve_workspace_dir(workspace_dir)
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        msg = f"path escapes workspace: {path}"
        raise ValueError(msg) from exc
    return resolved


def resolve_source_dir(source_dir: Path) -> Path:
    return source_dir.expanduser().resolve()


def resolve_source_path(source_dir: Path, source_path: str) -> Path:
    stripped = source_path.strip()
    if not stripped:
        msg = "source path must not be empty"
        raise ValueError(msg)

    root = resolve_source_dir(source_dir)
    raw = Path(stripped)
    if raw.is_absolute():
        candidate = raw.expanduser().resolve()
    else:
        candidate = (root / raw).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        msg = "Source path must be inside configured source_dir."
        raise ValueError(msg) from exc
    return candidate


def validate_txt_source_path(path: Path) -> None:
    if path.is_dir():
        return
    if path.suffix == ".txt":
        return
    msg = "Only .txt files and directories are supported for this endpoint."
    raise ValueError(msg)
