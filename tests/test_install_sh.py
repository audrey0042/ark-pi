"""Subprocess tests for install.sh planner and app bootstrap."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
FAKE_BIN = REPO_ROOT / "tests" / "fixtures" / "install_helpers"


def run_install(
    *args: str,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["sh", str(INSTALL_SH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        env=merged,
        check=False,
    )


def fake_helper_env(local_repo: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": f"{FAKE_BIN}:{os.environ.get('PATH', '')}",
        "ARK_INSTALL_LOCAL_REPO": str(local_repo),
    }
    if extra:
        env.update(extra)
    return env


def test_install_sh_is_executable() -> None:
    assert INSTALL_SH.is_file()
    assert INSTALL_SH.stat().st_mode & 0o111


def test_help_exits_zero_and_prints_usage() -> None:
    result = run_install("--help")
    assert result.returncode == 0
    assert "bootstrap" in result.stdout.lower()
    assert "--role" in result.stdout
    assert "--dry-run" in result.stdout
    assert "systemd" in result.stdout.lower() or "service" in result.stdout.lower()


@pytest.mark.parametrize("role", ["rag", "llm", "both"])
def test_role_dry_run_exits_zero(role: str) -> None:
    result = run_install("--role", role, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Dry run" in result.stdout
    assert "No changes were made." in result.stdout


def test_role_equals_form_dry_run() -> None:
    result = run_install("--role=rag", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "App bootstrap steps:" in result.stdout


def test_invalid_role_exits_nonzero() -> None:
    result = run_install("--role", "nope", "--dry-run")
    assert result.returncode != 0
    assert "unsupported role" in result.stderr.lower() or "unsupported role" in result.stdout.lower()


def test_unknown_flag_exits_nonzero() -> None:
    result = run_install("--unknown")
    assert result.returncode != 0
    assert "unknown flag" in result.stderr.lower()


def test_missing_role_non_interactive_exits_nonzero() -> None:
    result = run_install("--dry-run")
    assert result.returncode != 0
    assert "--role is required" in result.stderr


def test_piped_stdin_without_role_exits_nonzero() -> None:
    result = run_install("--dry-run", input_text="1\n")
    assert result.returncode != 0
    assert "--role is required" in result.stderr


@pytest.mark.parametrize("role", ["rag", "llm", "both"])
def test_dry_run_does_not_create_prefix_or_data_dir(role: str, tmp_path: Path) -> None:
    prefix = tmp_path / "ark-pi-prefix"
    data_dir = tmp_path / "ark-pi-data"
    assert not prefix.exists()
    assert not data_dir.exists()

    result = run_install(
        "--role",
        role,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert str(prefix) in result.stdout
    assert str(data_dir) in result.stdout
    assert not prefix.exists()
    assert not data_dir.exists()


def test_dry_run_includes_clone_venv_and_data_dirs() -> None:
    result = run_install("--role", "rag", "--dry-run")
    assert result.returncode == 0
    assert "Clone or update" in result.stdout
    assert "virtualenv" in result.stdout.lower()
    assert "pip install" in result.stdout
    assert "data/workspace" in result.stdout


def test_non_interactive_mutation_without_yes_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
    )
    assert result.returncode != 0
    assert "--yes" in result.stderr or "non-interactive" in result.stderr.lower()


def test_rag_yes_creates_rag_data_dirs_only(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (prefix / ".venv" / ".ark_installed").is_file()
    assert (data_dir / "data" / "workspace").is_dir()
    assert (data_dir / "data" / "sources").is_dir()
    assert not (data_dir / "models").exists()
    assert "App bootstrap complete." in result.stdout


def test_llm_yes_creates_model_dir_only(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (data_dir / "models").is_dir()
    assert not (data_dir / "data").exists()


def test_both_yes_creates_rag_and_llm_dirs(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "both",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (data_dir / "data" / "workspace").is_dir()
    assert (data_dir / "data" / "sources").is_dir()
    assert (data_dir / "models").is_dir()


def test_safe_install_writes_only_under_prefix_and_data_dir(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    outside = tmp_path / "outside"
    outside.mkdir()
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert list(outside.iterdir()) == []
    assert prefix.exists()
    assert data_dir.exists()


def test_existing_non_git_nonempty_prefix_fails(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    prefix.mkdir()
    (prefix / "existing.txt").write_text("stay", encoding="utf-8")
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode != 0
    assert "not a git checkout" in result.stderr.lower() or "not a git checkout" in result.stdout.lower()


def test_existing_git_checkout_with_local_changes_fails(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT, {"ARK_INSTALL_GIT_DIRTY": "1"})
    prefix.mkdir()
    (prefix / ".git").mkdir()

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode != 0
    assert "local changes" in result.stderr.lower() or "local changes" in result.stdout.lower()


def test_yes_flag_accepted_in_dry_run() -> None:
    result = run_install("--role", "rag", "--yes", "--dry-run")
    assert result.returncode == 0
    assert "Yes:" in result.stdout


def test_extra_positional_argument_rejected() -> None:
    result = run_install("--role", "rag", "--dry-run", "extra")
    assert result.returncode != 0


@pytest.mark.skipif(
    subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip() != "Linux",
    reason="Linux-only platform check",
)
def test_linux_platform_succeeds() -> None:
    result = run_install("--role", "rag", "--dry-run")
    assert result.returncode == 0
    assert "Detected OS:" in result.stdout
    assert "Linux" in result.stdout
