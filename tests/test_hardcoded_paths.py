"""Regression audit: block user-specific and legacy wrong defaults in tracked sources."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = frozenset({".git", ".venv", "__pycache__", ".pytest_cache"})

FORBIDDEN_IN_RUNTIME = (
    re.compile(r"/home/audrey"),
    re.compile(r"/Users/"),
    re.compile(r"/mnt/data"),
    re.compile(r"/run/media/audrey"),
    re.compile(r"/opt/llama\.cpp"),
    re.compile(r"/tmp/ark-pi"),
    re.compile(r'LLAMA_DIR="\$PREFIX/vendor/llama\.cpp"'),
    re.compile(r"/opt/ark-pi/vendor/llama\.cpp"),
)

FORBIDDEN_IN_DOCS = (
    re.compile(r"/home/audrey"),
    re.compile(r"/Users/"),
    re.compile(r"/mnt/data"),
    re.compile(r"/run/media/audrey"),
    re.compile(r"/opt/llama\.cpp"),
    re.compile(r"/tmp/ark-pi"),
    re.compile(r"/opt/ark-pi/vendor/llama\.cpp"),
)

# Only test_hardcoded_paths.py may contain synthetic forbidden strings for self-tests.
AUDIT_SELF_TEST_FIXTURE = "/home/audrey/projects/ark-pi"


def _iter_files(root: Path, *, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if not path.is_file():
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        files.append(path)
    return files


def _path_label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _find_forbidden_matches(
    paths: list[Path],
    patterns: tuple[re.Pattern[str], ...],
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                if pattern.search(line):
                    violations.append(f"{_path_label(path)}:{line_no}: {line.strip()}")
    return violations


def test_install_sh_default_llama_dir_uses_data_dir() -> None:
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'LLAMA_DIR="$DATA_DIR/vendor/llama.cpp"' in text
    assert 'LLAMA_DIR="$PREFIX/vendor/llama.cpp"' not in text


def test_templates_default_llama_bin_under_data_dir() -> None:
    text = (REPO_ROOT / "src" / "ark_pi" / "deploy" / "templates.py").read_text(encoding="utf-8")
    assert 'DEFAULT_LLM_BIN = "/srv/ark-pi/vendor/llama.cpp/build/bin/llama-server"' in text
    assert "/opt/ark-pi/vendor/llama.cpp" not in text


def test_runtime_and_installer_have_no_forbidden_paths() -> None:
    paths = [REPO_ROOT / "install.sh", *_iter_files(REPO_ROOT / "src" / "ark_pi", suffixes=(".py",))]
    violations = _find_forbidden_matches(paths, FORBIDDEN_IN_RUNTIME)
    assert not violations, "Forbidden paths in runtime/installer:\n" + "\n".join(violations)


def test_docs_have_no_forbidden_paths() -> None:
    paths = [REPO_ROOT / "README.md", *_iter_files(REPO_ROOT / "docs", suffixes=(".md",))]
    violations = _find_forbidden_matches(paths, FORBIDDEN_IN_DOCS)
    assert not violations, "Forbidden paths in docs:\n" + "\n".join(violations)


def test_tests_have_no_forbidden_paths_except_audit_module() -> None:
    paths = [
        path
        for path in _iter_files(REPO_ROOT / "tests", suffixes=(".py",))
        if path.name != "test_hardcoded_paths.py"
    ]
    violations = _find_forbidden_matches(paths, FORBIDDEN_IN_RUNTIME)
    assert not violations, "Forbidden paths in tests:\n" + "\n".join(violations)


def test_audit_helper_detects_forbidden_pattern(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text(f"bad path {AUDIT_SELF_TEST_FIXTURE}\n", encoding="utf-8")
    matches = _find_forbidden_matches([sample], FORBIDDEN_IN_RUNTIME)
    assert any("/home/audrey" in match for match in matches)
