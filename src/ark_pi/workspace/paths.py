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


def resolve_workspace_dir(workspace_dir: Path) -> Path:
    return workspace_dir.expanduser().resolve()


def index_paths(workspace_dir: Path, slug: str) -> tuple[Path, Path]:
    root = resolve_workspace_dir(workspace_dir)
    index_root = root / "indexes" / slug
    chunks_path = index_root / "chunks.jsonl"
    index_dir = index_root / "index"
    ensure_path_inside_workspace(root, chunks_path)
    ensure_path_inside_workspace(root, index_dir)
    return chunks_path, index_dir


def ensure_path_inside_workspace(workspace_dir: Path, path: Path) -> Path:
    root = resolve_workspace_dir(workspace_dir)
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        msg = f"path escapes workspace: {path}"
        raise ValueError(msg) from exc
    return resolved
