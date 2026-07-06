"""Subprocess tests for install.sh planner, app bootstrap, and deploy render."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
FAKE_BIN = REPO_ROOT / "tests" / "fixtures" / "install_helpers"
TINY_MODEL = REPO_ROOT / "tests" / "fixtures" / "models" / "tiny-q4km.gguf"
TINY_MODEL_SHA = "370df1c551a1dabfdbce83ed2231e9022e9c0bb10d5df3ac0d96b820389d24f4"
TINY_WRONG_MODEL = REPO_ROOT / "tests" / "fixtures" / "models" / "tiny-wrong.gguf"
TINY_WRONG_SHA = "317cb23cdee1be02c067386916817e9874308daacb9387d371c9ecca377c38ed"

EXPECTED_LLM_APT_PACKAGES = ("cmake", "libcurl4-openssl-dev", "ccache")
LLAMA_STUB = REPO_ROOT / "tests" / "fixtures" / "llama.cpp_stub"
EXPECTED_APT_PACKAGES = (
    "ca-certificates",
    "curl",
    "git",
    "python3",
    "python3-venv",
    "python3-pip",
    "python3-dev",
    "build-essential",
    "pkg-config",
    "rsync",
    "unzip",
    "jq",
)


def run_install(
    *args: str,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["/bin/sh", str(INSTALL_SH), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        env=merged,
        check=False,
    )


def fake_helper_env(
    local_repo: Path,
    extra: dict[str, str] | None = None,
    render_log: Path | None = None,
    command_log: Path | None = None,
) -> dict[str, str]:
    env = {
        "PATH": f"{FAKE_BIN}:{os.environ.get('PATH', '')}",
        "ARK_INSTALL_LOCAL_REPO": str(local_repo),
        "ARK_PI_INSTALL_TEST_EUID": "1000",
    }
    if render_log is not None:
        env["ARK_INSTALL_RENDER_LOG"] = str(render_log)
    if command_log is not None:
        env["ARK_PI_INSTALL_COMMAND_LOG"] = str(command_log)
    if extra:
        env.update(extra)
    return env


def read_command_log(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def copy_repo_tree(source: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        source,
        dest,
        ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "*.pyc"),
    )


def seed_existing_git_checkout(prefix: Path, source: Path) -> None:
    copy_repo_tree(source, prefix)
    (prefix / ".git").mkdir()


def test_install_sh_is_executable() -> None:
    assert INSTALL_SH.is_file()
    assert INSTALL_SH.stat().st_mode & 0o111


def test_help_exits_zero_and_prints_usage() -> None:
    result = run_install("--help")
    assert result.returncode == 0
    assert "bootstrap" in result.stdout.lower()
    assert "--role" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--generated-dir" in result.stdout
    assert "--install-services" in result.stdout
    assert "--no-os-packages" in result.stdout
    assert "--validate-only" in result.stdout
    assert "--no-validate" in result.stdout
    assert "--llama-build" in result.stdout
    assert "--require-model" in result.stdout
    assert "--download-model" in result.stdout


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


@pytest.mark.parametrize(
    ("role", "deploy_role"),
    [("rag", "rag"), ("llm", "llm"), ("both", "all")],
)
def test_dry_run_prints_deploy_render_command(role: str, deploy_role: str, tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    result = run_install(
        "--role",
        role,
        "--generated-dir",
        str(generated),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "deploy render" in result.stdout
    assert f"--role {deploy_role}" in result.stdout
    assert str(generated) in result.stdout
    assert not generated.exists()


def test_dry_run_does_not_create_prefix_data_or_generated_dirs(tmp_path: Path) -> None:
    prefix = tmp_path / "ark-pi-prefix"
    data_dir = tmp_path / "ark-pi-data"
    generated = tmp_path / "ark-pi-generated"
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert not prefix.exists()
    assert not data_dir.exists()
    assert not generated.exists()


def test_dry_run_prints_apt_package_plan() -> None:
    result = run_install("--role", "rag", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "apt-get update" in result.stdout
    for package in EXPECTED_APT_PACKAGES:
        assert package in result.stdout


def test_dry_run_does_not_call_fake_apt_get(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)
    result = run_install("--role", "rag", "--dry-run", env=env)
    assert result.returncode == 0, result.stderr
    assert read_command_log(command_log) == ""


def test_no_os_packages_dry_run_skips_apt_install_line() -> None:
    result = run_install("--role", "rag", "--no-os-packages", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Skip apt package install" in result.stdout


def test_package_manager_none_dry_run() -> None:
    result = run_install("--role", "rag", "--package-manager", "none", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "resolved: none" in result.stdout


def test_package_manager_missing_value_exits_nonzero() -> None:
    result = run_install("--package-manager")
    assert result.returncode != 0
    assert "missing value" in result.stderr.lower()


def test_package_manager_invalid_exits_nonzero() -> None:
    result = run_install("--role", "rag", "--package-manager", "yum", "--dry-run")
    assert result.returncode != 0
    assert "unsupported" in result.stderr.lower()


def test_package_manager_auto_and_apt_accepted_dry_run() -> None:
    assert run_install("--role", "rag", "--package-manager", "auto", "--dry-run").returncode == 0
    assert run_install("--role", "rag", "--package-manager", "apt", "--dry-run").returncode == 0


def test_apt_install_runs_before_git_clone(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)

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
    log = read_command_log(command_log)
    assert "apt-get update" in log
    assert "apt-get install -y" in log
    for package in EXPECTED_APT_PACKAGES:
        assert package in log
    assert log.index("apt-get update") < log.index("git clone")


def test_no_os_packages_skips_apt_get(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--no-os-packages",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "apt-get" not in read_command_log(command_log)


def test_package_manager_none_skips_apt_get(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--repo",
        "file://fake",
        "--package-manager",
        "none",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "apt-get" not in read_command_log(command_log)


def test_apt_install_failure_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT, {"ARK_PI_INSTALL_APT_FAIL": "1"})

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
    assert "apt-get" in result.stderr.lower()


def test_non_root_uses_sudo_for_apt_get(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(
        REPO_ROOT,
        command_log=command_log,
        extra={"ARK_PI_INSTALL_TEST_EUID": "1000"},
    )

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
    log = read_command_log(command_log)
    assert "sudo apt-get update" in log
    assert "sudo apt-get install -y" in log


def test_root_does_not_use_sudo_for_apt_get(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(
        REPO_ROOT,
        command_log=command_log,
        extra={"ARK_PI_INSTALL_TEST_EUID": "0"},
    )

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
    log = read_command_log(command_log)
    assert not any(line.startswith("sudo ") for line in log.splitlines())
    assert "apt-get update" in log


def test_sudo_required_but_missing_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(
        REPO_ROOT,
        extra={
            "ARK_PI_INSTALL_TEST_EUID": "1000",
            "ARK_PI_INSTALL_TEST_NO_SUDO": "1",
        },
    )

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
    assert "sudo required" in result.stderr.lower()


def test_package_manager_none_missing_commands_shows_guidance(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()
    uname = empty_bin / "uname"
    uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; esac\n', encoding="utf-8")
    uname.chmod(0o755)
    env = fake_helper_env(REPO_ROOT)
    env["PATH"] = str(empty_bin)
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(tmp_path / "prefix"),
        "--data-dir",
        str(tmp_path / "data"),
        "--package-manager",
        "none",
        "--yes",
        env=env,
    )
    assert result.returncode != 0
    assert "Install these packages manually" in result.stderr
    for package in EXPECTED_APT_PACKAGES:
        assert package in result.stderr


def test_dry_run_includes_clone_venv_render_and_data_dirs() -> None:
    result = run_install("--role", "rag", "--dry-run")
    assert result.returncode == 0
    assert "Clone or update" in result.stdout
    assert "virtualenv" in result.stdout.lower()
    assert "pip install" in result.stdout
    assert "data/workspace" in result.stdout
    assert "deploy render" in result.stdout


def test_generated_dir_equals_form_dry_run(tmp_path: Path) -> None:
    generated = tmp_path / "gen"
    result = run_install(f"--generated-dir={generated}", "--role", "rag", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert str(generated) in result.stdout


def test_generated_dir_missing_value_exits_nonzero() -> None:
    result = run_install("--generated-dir")
    assert result.returncode != 0
    assert "missing value" in result.stderr.lower()


def test_generated_dir_under_etc_rejected() -> None:
    result = run_install("--role", "rag", "--generated-dir", "/etc/ark-pi/generated", "--dry-run")
    assert result.returncode != 0
    assert "unsafe generated dir" in result.stderr.lower() or "generated dir" in result.stderr.lower()


def test_generated_dir_under_unrelated_opt_rejected(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(tmp_path / "data"),
        "--generated-dir",
        "/opt/other/generated",
        "--dry-run",
    )
    assert result.returncode != 0
    assert "generated dir" in result.stderr.lower()


def test_generated_dir_under_prefix_allowed(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    generated = prefix / "deploy" / "generated"
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(tmp_path / "data"),
        "--generated-dir",
        str(generated),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr


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


@pytest.mark.parametrize(
    ("role", "deploy_role"),
    [("rag", "rag"), ("llm", "llm"), ("both", "all")],
)
def test_safe_install_calls_deploy_render(
    role: str,
    deploy_role: str,
    tmp_path: Path,
) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    render_log = tmp_path / "render.log"
    env = fake_helper_env(REPO_ROOT, render_log=render_log)

    result = run_install(
        "--role",
        role,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert generated.is_dir()
    assert (generated / ".rendered").is_file()
    log = render_log.read_text(encoding="utf-8")
    assert f"--role {deploy_role}" in log
    assert f"--output-dir {generated}" in log
    assert "App bootstrap complete." in result.stdout
    assert str(generated) in result.stdout


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
    assert (data_dir / "deploy" / "generated" / ".rendered").is_file()


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


def test_render_failure_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = fake_helper_env(REPO_ROOT, {"ARK_INSTALL_RENDER_FAIL": "1"})

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
    assert "deploy render failed" in result.stderr.lower()


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


def test_existing_checkout_behind_origin_fast_forwards_before_pip(tmp_path: Path) -> None:
    current = tmp_path / "current"
    stale = tmp_path / "stale"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    copy_repo_tree(REPO_ROOT, stale)
    copy_repo_tree(REPO_ROOT, current)
    marker = current / ".install_ff_test_marker"
    marker.write_text("new", encoding="utf-8")
    seed_existing_git_checkout(prefix, stale)
    assert not (prefix / ".install_ff_test_marker").exists()
    env = fake_helper_env(
        current,
        extra={"ARK_INSTALL_GIT_BEHIND": "1"},
        command_log=command_log,
    )
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--no-os-packages",
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (prefix / ".install_ff_test_marker").read_text(encoding="utf-8") == "new"
    log = read_command_log(command_log)
    assert "merge --ff-only" in log
    assert "pip install" in log
    assert log.index("merge --ff-only") < log.index("pip install")


def test_existing_checkout_diverged_fails_before_pip(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    seed_existing_git_checkout(prefix, REPO_ROOT)
    env = fake_helper_env(REPO_ROOT, {"ARK_INSTALL_GIT_DIVERGED": "1"})
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--no-os-packages",
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert "fast-forward" in combined or "diverged" in combined


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


def test_dry_run_without_install_services_no_service_plan_details() -> None:
    result = run_install("--role", "rag", "--dry-run")
    assert result.returncode == 0
    assert "Install services:      no" in result.stdout
    assert "Service file install steps:" not in result.stdout


def test_dry_run_with_install_services_prints_service_plan(tmp_path: Path) -> None:
    service_root = tmp_path / "service-root"
    result = run_install(
        "--role",
        "rag",
        "--service-root",
        str(service_root),
        "--install-services",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "Service file install steps:" in result.stdout
    assert "ark-rag.env" in result.stdout
    assert "ark-rag.service" in result.stdout
    assert not service_root.exists()


def test_dry_run_both_install_services_mentions_all_four_files() -> None:
    result = run_install("--role", "both", "--install-services", "--dry-run")
    assert result.returncode == 0
    assert "ark-rag.env" in result.stdout
    assert "ark-llm.service" in result.stdout


def test_service_root_equals_form_dry_run(tmp_path: Path) -> None:
    service_root = tmp_path / "svc"
    result = run_install(
        f"--service-root={service_root}",
        "--role",
        "rag",
        "--install-services",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr


def test_service_root_missing_value_exits_nonzero() -> None:
    result = run_install("--service-root")
    assert result.returncode != 0
    assert "missing value" in result.stderr.lower()


def test_invalid_service_root_rejected() -> None:
    result = run_install("--role", "rag", "--service-root", "/etc", "--install-services", "--dry-run")
    assert result.returncode != 0
    assert "service root" in result.stderr.lower()


def test_non_interactive_install_services_without_yes_exits_nonzero(tmp_path: Path) -> None:
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(tmp_path / "prefix"),
        "--data-dir",
        str(tmp_path / "data"),
        "--service-root",
        str(tmp_path / "svc"),
        "--install-services",
    )
    assert result.returncode != 0
    assert "--yes" in result.stderr or "non-interactive" in result.stderr.lower()


def _run_service_install(
    tmp_path: Path,
    role: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT, extra=extra_env)
    return run_install(
        "--role",
        role,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--service-root",
        str(service_root),
        "--repo",
        "file://fake",
        "--install-services",
        "--yes",
        env=env,
    )


def test_rag_service_install_copies_files(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "rag")
    assert result.returncode == 0, result.stderr
    service_root = tmp_path / "service-root"
    env_file = service_root / "etc" / "ark-pi" / "ark-rag.env"
    svc_file = service_root / "etc" / "systemd" / "system" / "ark-rag.service"
    assert env_file.is_file()
    assert svc_file.is_file()
    assert env_file.read_text(encoding="utf-8") == (
        "ARK_ROLE=rag\nARK_WORKSPACE_DIR=/generated/rag/workspace\n"
    )
    assert not (service_root / "etc" / "ark-pi" / "ark-llm.env").exists()


def test_llm_service_install_copies_files(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "llm")
    assert result.returncode == 0, result.stderr
    service_root = tmp_path / "service-root"
    assert (service_root / "etc" / "ark-pi" / "ark-llm.env").is_file()
    assert (service_root / "etc" / "systemd" / "system" / "ark-llm.service").is_file()
    assert not (service_root / "etc" / "ark-pi" / "ark-rag.env").exists()


def test_both_service_install_copies_all_four_files(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "both")
    assert result.returncode == 0, result.stderr
    service_root = tmp_path / "service-root"
    for name in ("ark-rag.env", "ark-rag.service", "ark-llm.env", "ark-llm.service"):
        if name.endswith(".env"):
            assert (service_root / "etc" / "ark-pi" / name).is_file()
        else:
            assert (service_root / "etc" / "systemd" / "system" / name).is_file()


def test_service_files_have_expected_modes(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "rag")
    assert result.returncode == 0, result.stderr
    service_root = tmp_path / "service-root"
    env_mode = oct((service_root / "etc" / "ark-pi" / "ark-rag.env").stat().st_mode & 0o777)
    svc_mode = oct((service_root / "etc" / "systemd" / "system" / "ark-rag.service").stat().st_mode & 0o777)
    assert env_mode.endswith("640")
    assert svc_mode.endswith("644")


def test_existing_service_files_are_backed_up(tmp_path: Path) -> None:
    service_root = tmp_path / "service-root"
    existing = service_root / "etc" / "ark-pi" / "ark-rag.env"
    existing.parent.mkdir(parents=True)
    existing.write_text("old content", encoding="utf-8")

    result = _run_service_install(tmp_path, "rag")
    assert result.returncode == 0, result.stderr
    assert existing.read_text(encoding="utf-8") == (
        "ARK_ROLE=rag\nARK_WORKSPACE_DIR=/generated/rag/workspace\n"
    )
    backups = list((service_root / "etc" / "ark-pi").glob("ark-rag.env.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "old content"


def test_redirected_service_root_skips_systemctl_message(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "rag")
    assert result.returncode == 0, result.stderr
    assert "Skipping systemctl" in result.stdout


def test_missing_generated_service_files_exits_nonzero(tmp_path: Path) -> None:
    result = _run_service_install(tmp_path, "rag", extra_env={"ARK_INSTALL_RENDER_SKIP_TEMPLATES": "1"})
    assert result.returncode != 0
    assert "missing generated service file" in result.stderr.lower()


def test_without_install_services_no_service_root_writes(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT)

    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--service-root",
        str(service_root),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not service_root.exists()


def _run_rag_install(
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
    command_log: Path | None = None,
    no_validate: bool = False,
) -> subprocess.CompletedProcess[str]:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=command_log)
    args = [
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
    ]
    if no_validate:
        args.append("--no-validate")
    return run_install(*args, env=env)


def _validate_only(
    tmp_path: Path,
    role: str,
    *,
    prefix: Path,
    data_dir: Path,
    generated: Path,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    command_log: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=command_log)
    args = [
        "--role",
        role,
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
    ]
    if extra_args:
        args.extend(extra_args)
    return run_install(*args, env=env)


def test_validate_only_happy_path_rag(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    result = _validate_only(tmp_path, "rag", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode == 0, result.stderr
    assert "[pass]" in result.stdout
    assert "Validation: PASS" in result.stdout


def test_validate_only_happy_path_llm_warns_missing_gguf(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = _validate_only(tmp_path, "llm", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode == 0, result.stderr
    assert "[warning] model_file" in result.stdout
    assert "Validation: PASS (with warnings)" in result.stdout


def test_validate_only_happy_path_both(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "both",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = _validate_only(tmp_path, "both", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode == 0, result.stderr
    assert "[pass] deploy_templates" in result.stdout


def test_validate_only_missing_prefix_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "missing-prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "generated"
    generated.mkdir(parents=True)
    result = _validate_only(tmp_path, "rag", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode != 0
    assert "[fail] prefix_exists" in result.stdout


def test_validate_only_missing_ark_exits_nonzero(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "generated"
    prefix.mkdir()
    data_dir.mkdir()
    generated.mkdir()
    result = _validate_only(tmp_path, "rag", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode != 0
    assert "[fail] venv_ark" in result.stdout


def test_validate_only_missing_data_dir_exits_nonzero(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "missing-data"
    generated = tmp_path / "data" / "deploy" / "generated"
    result = _validate_only(tmp_path, "rag", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode != 0
    assert "[fail] data_dir" in result.stdout


def test_validate_only_missing_generated_templates_exits_nonzero(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    (generated / "ark-rag.env").unlink()
    (generated / "ark-rag.service").unlink()
    result = _validate_only(tmp_path, "rag", prefix=prefix, data_dir=data_dir, generated=generated)
    assert result.returncode != 0
    assert "[fail] deploy_templates" in result.stdout


def test_validate_only_deploy_preflight_failure_exits_nonzero(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_env={"ARK_INSTALL_PREFLIGHT_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "[fail] deploy_preflight" in result.stdout


def test_validate_only_service_files_under_tmp_service_root(tmp_path: Path) -> None:
    install = _run_service_install(tmp_path, "rag")
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=["--service-root", str(service_root)],
    )
    assert result.returncode == 0, result.stderr
    assert "[pass] service_env_files" in result.stdout
    assert "[pass] service_unit_files" in result.stdout


def test_validate_only_missing_service_file_with_install_services_exits_nonzero(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=["--install-services", "--service-root", str(service_root)],
    )
    assert result.returncode != 0
    assert "[fail] service_env_files" in result.stdout


def test_redirected_service_root_validation_does_not_call_systemctl(tmp_path: Path) -> None:
    install = _run_service_install(tmp_path, "rag")
    assert install.returncode == 0, install.stderr
    command_log = tmp_path / "commands.log"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=["--service-root", str(service_root)],
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    assert "systemctl" not in read_command_log(command_log)


def test_validation_with_fake_systemctl_records_read_only_checks(tmp_path: Path) -> None:
    install = _run_service_install(tmp_path, "rag")
    assert install.returncode == 0, install.stderr
    command_log = tmp_path / "commands.log"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=["--service-root", str(service_root), "--install-services"],
        extra_env={"ARK_PI_INSTALL_TEST_SYSTEMCTL_ROOT": "1"},
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "systemctl is-enabled ark-rag.service" in log
    assert "systemctl is-active ark-rag.service" in log
    assert "systemctl enable" not in log
    assert "systemctl start" not in log


def test_post_install_validation_runs_by_default(tmp_path: Path) -> None:
    result = _run_rag_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Running post-install validation" in result.stdout
    assert "Validation: PASS" in result.stdout


def test_no_validate_skips_post_install_validation(tmp_path: Path) -> None:
    result = _run_rag_install(tmp_path, no_validate=True)
    assert result.returncode == 0, result.stderr
    assert "Running post-install validation" not in result.stdout
    assert "Post-install validation: skipped (--no-validate)" in result.stdout
    assert "--validate-only" in result.stdout


def test_dry_run_does_not_run_validation_commands(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(tmp_path / "prefix"),
        "--data-dir",
        str(tmp_path / "data"),
        "--repo",
        "file://fake",
        "--yes",
        "--dry-run",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Post-install validation: will run" in result.stdout
    assert read_command_log(command_log) == ""


def test_dry_run_validate_only_prints_validation_plan() -> None:
    result = run_install("--role", "rag", "--validate-only", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Validation steps:" in result.stdout
    assert "deploy preflight" in result.stdout


def fake_system_root_env(
    tmp_path: Path,
    local_repo: Path,
    *,
    extra: dict[str, str] | None = None,
    render_log: Path | None = None,
    command_log: Path | None = None,
    unwritable_parents: bool = True,
) -> tuple[dict[str, str], Path]:
    system_root = tmp_path / "system-root"
    (system_root / "opt").mkdir(parents=True)
    (system_root / "srv").mkdir(parents=True)
    if unwritable_parents:
        (system_root / "opt").chmod(0o555)
        (system_root / "srv").chmod(0o555)
    env = fake_helper_env(
        local_repo,
        extra=extra,
        render_log=render_log,
        command_log=command_log,
    )
    env["ARK_PI_INSTALL_TEST_SYSTEM_ROOT"] = str(system_root)
    return env, system_root


def test_dry_run_default_paths_prints_ownership_plan() -> None:
    env = fake_helper_env(
        REPO_ROOT,
        extra={
            "ARK_PI_INSTALL_TEST_UNWRITABLE_PREFIX_PARENT": "1",
            "ARK_PI_INSTALL_TEST_UNWRITABLE_DATA_DIR_PARENT": "1",
        },
    )
    result = run_install("--role", "rag", "--dry-run", env=env)
    assert result.returncode == 0, result.stderr
    assert "Install path ownership steps:" in result.stdout
    assert "Install owner:" in result.stdout
    assert "/opt/ark-pi" in result.stdout
    assert "/srv/ark-pi" in result.stdout
    assert "sudo mkdir -p" in result.stdout
    assert "sudo chown" in result.stdout


def test_dry_run_ownership_plan_creates_nothing(tmp_path: Path) -> None:
    env, system_root = fake_system_root_env(tmp_path, REPO_ROOT)
    result = run_install("--role", "rag", "--dry-run", env=env)
    assert result.returncode == 0, result.stderr
    assert "Install path ownership steps:" in result.stdout
    assert not (system_root / "opt" / "ark-pi").exists()
    assert not (system_root / "srv" / "ark-pi").exists()


def test_system_root_install_prepares_paths_and_bootstraps(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env, system_root = fake_system_root_env(
        tmp_path,
        REPO_ROOT,
        command_log=command_log,
    )
    result = run_install(
        "--role",
        "rag",
        "--no-os-packages",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (system_root / "opt" / "ark-pi").is_dir()
    assert (system_root / "srv" / "ark-pi").is_dir()
    assert (system_root / "opt" / "ark-pi" / ".venv" / ".ark_installed").is_file()
    log = read_command_log(command_log)
    assert "sudo mkdir -p" in log
    assert "sudo chown" in log
    assert "git clone" in log
    assert log.index("mkdir -p") < log.index("git clone")
    for line in log.splitlines():
        if "chown" in line:
            assert "ark-pi" in line
            assert not line.rstrip().endswith("/opt")
            assert not line.rstrip().endswith("/srv")


def test_tmp_prefix_skips_ownership_sudo(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--no-os-packages",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "chown" not in log
    assert "sudo mkdir -p" not in log


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--prefix", "/opt"),
        ("--prefix", "/"),
        ("--data-dir", "/srv"),
        ("--data-dir", "/"),
    ],
)
def test_unsafe_install_path_rejected(
    flag: str,
    value: str,
    tmp_path: Path,
) -> None:
    if flag == "--prefix":
        other = ("--data-dir", str(tmp_path / "data"))
    else:
        other = ("--prefix", str(tmp_path / "prefix"))
    env = fake_helper_env(REPO_ROOT)
    result = run_install(
        "--role",
        "rag",
        flag,
        value,
        other[0],
        other[1],
        "--no-os-packages",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode != 0
    assert "refusing unsafe install path" in result.stderr.lower()


def test_ownership_prep_without_sudo_fails_before_clone(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(
        REPO_ROOT,
        command_log=command_log,
        extra={
            "ARK_PI_INSTALL_TEST_NO_SUDO": "1",
            "ARK_PI_INSTALL_TEST_UNWRITABLE_PREFIX_PARENT": "1",
            "ARK_PI_INSTALL_TEST_UNWRITABLE_DATA_DIR_PARENT": "1",
        },
    )
    result = run_install(
        "--role",
        "rag",
        "--no-os-packages",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode != 0
    assert "sudo required" in result.stderr.lower()
    assert "git clone" not in read_command_log(command_log)


def test_chown_failure_fails_before_clone(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env, _system_root = fake_system_root_env(
        tmp_path,
        REPO_ROOT,
        command_log=command_log,
        extra={"ARK_PI_INSTALL_CHOWN_FAIL": "1"},
    )
    result = run_install(
        "--role",
        "rag",
        "--no-os-packages",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode != 0
    assert "chown" in result.stderr.lower()
    assert "git clone" not in read_command_log(command_log)


def test_validation_output_includes_pass_warning_fail_labels(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_env={"ARK_INSTALL_LLM_STATUS_FAIL": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "[pass]" in result.stdout
    assert "[warning]" in result.stdout
    assert "[fail]" not in result.stdout


RAG_SERVICE_ENV = (
    "ARK_ROLE=rag\n"
    "ARK_WORKSPACE_DIR=/service/rag/workspace\n"
    "ARK_SOURCE_DIR=/service/rag/sources\n"
)
RAG_GENERATED_ENV = (
    "ARK_ROLE=rag\n"
    "ARK_WORKSPACE_DIR=/generated/rag/workspace\n"
)
LLM_SERVICE_ENV = "ARK_ROLE=llm\nARK_MODEL_PATH=/service/llm/model.gguf\n"
LEGACY_LLM_SERVICE_ENV = (
    "ARK_ROLE=llm\n"
    "ARK_LLM_HOST=0.0.0.0\n"
    "ARK_LLM_PORT=8080\n"
    "ARK_LLAMACPP_SERVER_BIN=/legacy/bin/llama-server\n"
    "ARK_LLAMACPP_MODEL_PATH=/srv/ark-pi/models/model.gguf\n"
)
LLM_GENERATED_ENV = "ARK_ROLE=llm\nARK_MODEL_PATH=/generated/llm/model.gguf\n"


def _write_env(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_rag_install_with_command_log(
    tmp_path: Path,
    *,
    install_services: bool = False,
    service_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    command_log = tmp_path / "commands.log"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=command_log)
    args = [
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
    ]
    if install_services:
        args.extend(
            [
                "--service-root",
                str(service_root or tmp_path / "service-root"),
                "--install-services",
            ]
        )
    result = run_install(*args, env=env)
    return result, command_log, read_command_log(command_log)


def test_post_install_validation_without_services_uses_generated_rag_env(
    tmp_path: Path,
) -> None:
    result, _, log = _run_rag_install_with_command_log(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ark preflight env:" in log
    assert "ARK_WORKSPACE_DIR=/generated/rag/workspace" in log
    assert "/service/rag/workspace" not in log


def test_post_install_validation_with_services_uses_service_rag_env(tmp_path: Path) -> None:
    service_root = tmp_path / "service-root"
    result, _, log = _run_rag_install_with_command_log(
        tmp_path,
        install_services=True,
        service_root=service_root,
    )
    assert result.returncode == 0, result.stderr
    expected_env = str(service_root / "etc" / "ark-pi" / "ark-rag.env")
    assert expected_env in result.stdout
    assert "[pass] rag_preflight" in result.stdout
    assert "ark preflight env:" in log


def test_validate_only_install_services_uses_service_rag_env(tmp_path: Path) -> None:
    install = _run_service_install(tmp_path, "rag")
    assert install.returncode == 0, install.stderr
    service_root = tmp_path / "service-root"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    _write_env(service_root / "etc" / "ark-pi" / "ark-rag.env", RAG_SERVICE_ENV)
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=[
            "--service-root",
            str(service_root),
            "--install-services",
        ],
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "ARK_WORKSPACE_DIR=/service/rag/workspace" in log


def test_validate_only_without_services_uses_generated_rag_env(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "ARK_WORKSPACE_DIR=/generated/rag/workspace" in log


def test_validate_only_falls_back_to_service_env_when_generated_missing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "rag",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--service-root",
        str(service_root),
        "--install-services",
        "--no-validate",
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    _write_env(service_root / "etc" / "ark-pi" / "ark-rag.env", RAG_SERVICE_ENV)
    (generated / "ark-rag.env").unlink()
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=["--service-root", str(service_root)],
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    assert "[warning] role_env_file" in result.stdout
    log = read_command_log(command_log)
    assert "ARK_WORKSPACE_DIR=/service/rag/workspace" in log


def test_both_role_validation_uses_separate_env_files(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "both",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--service-root",
        str(service_root),
        "--install-services",
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    _write_env(service_root / "etc" / "ark-pi" / "ark-rag.env", RAG_SERVICE_ENV)
    _write_env(service_root / "etc" / "ark-pi" / "ark-llm.env", LLM_SERVICE_ENV)
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "both",
        prefix=prefix,
        data_dir=data_dir,
        generated=generated,
        extra_args=[
            "--service-root",
            str(service_root),
            "--install-services",
        ],
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "ARK_WORKSPACE_DIR=/service/rag/workspace" in log
    assert "ARK_MODEL_PATH=/service/llm/model.gguf" in log


def test_malformed_env_file_fails_before_ark_preflight(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    generated = tmp_path / "data" / "deploy" / "generated" / "ark-rag.env"
    generated.write_text("not-a-valid-env-line\n", encoding="utf-8")
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=tmp_path / "prefix",
        data_dir=tmp_path / "data",
        generated=tmp_path / "data" / "deploy" / "generated",
        command_log=command_log,
    )
    assert result.returncode != 0
    assert "[fail] role_env_parse" in result.stdout
    assert "ark preflight" not in read_command_log(command_log)


def test_missing_selected_env_file_fails_validation(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    generated = tmp_path / "data" / "deploy" / "generated" / "ark-rag.env"
    generated.unlink()
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=tmp_path / "prefix",
        data_dir=tmp_path / "data",
        generated=tmp_path / "data" / "deploy" / "generated",
    )
    assert result.returncode != 0
    assert "[fail] deploy_templates" in result.stdout or "[fail] role_env_file" in result.stdout


def test_unknown_env_keys_warn_and_allowlisted_keys_still_pass(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path)
    assert install.returncode == 0, install.stderr
    generated = tmp_path / "data" / "deploy" / "generated" / "ark-rag.env"
    generated.write_text(
        "ARK_ROLE=rag\n"
        "ARK_WORKSPACE_DIR=/generated/rag/workspace\n"
        "ARK_FUTURE_KEY=ignored\n",
        encoding="utf-8",
    )
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=tmp_path / "prefix",
        data_dir=tmp_path / "data",
        generated=tmp_path / "data" / "deploy" / "generated",
        command_log=command_log,
    )
    assert result.returncode == 0, result.stderr
    assert "[warning] role_env_unknown_keys" in result.stdout
    assert "ARK_FUTURE_KEY" in result.stdout
    log = read_command_log(command_log)
    assert "ARK_WORKSPACE_DIR=/generated/rag/workspace" in log
    assert "ARK_FUTURE_KEY" not in log


def _run_service_install_no_validate(
    tmp_path: Path,
    role: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT, extra=extra_env)
    return run_install(
        "--role",
        role,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--service-root",
        str(service_root),
        "--repo",
        "file://fake",
        "--install-services",
        "--no-validate",
        "--yes",
        env=env,
    )


def _run_real_service_root_rag_install(
    tmp_path: Path,
    *,
    command_log: Path | None = None,
    extra_env: dict[str, str] | None = None,
    no_validate: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], Path]:
    log_path = command_log or tmp_path / "commands.log"
    env, system_root = fake_system_root_env(
        tmp_path,
        REPO_ROOT,
        command_log=log_path,
        extra=extra_env,
    )
    args = [
        "--role",
        "rag",
        "--no-os-packages",
        "--install-services",
        "--service-root",
        "/",
        "--no-enable",
        "--no-start",
        "--repo",
        "file://fake",
        "--yes",
    ]
    if no_validate:
        args.append("--no-validate")
    result = run_install(*args, env=env)
    return result, env, system_root


def test_unreadable_generated_env_fails_before_ark_preflight(tmp_path: Path) -> None:
    install = _run_rag_install(tmp_path, no_validate=True)
    assert install.returncode == 0, install.stderr
    generated = tmp_path / "data" / "deploy" / "generated" / "ark-rag.env"
    generated.chmod(0o000)
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=tmp_path / "prefix",
        data_dir=tmp_path / "data",
        generated=tmp_path / "data" / "deploy" / "generated",
        command_log=command_log,
    )
    assert result.returncode != 0
    assert "[fail] role_env_read" in result.stdout
    assert "[pass] rag_preflight" not in result.stdout
    assert "ark preflight" not in read_command_log(command_log)


def test_unreadable_redirected_service_env_fails_without_sudo(tmp_path: Path) -> None:
    install = _run_service_install_no_validate(tmp_path, "rag")
    assert install.returncode == 0, install.stderr
    service_root = tmp_path / "service-root"
    env_file = service_root / "etc" / "ark-pi" / "ark-rag.env"
    env_file.chmod(0o000)
    command_log = tmp_path / "commands.log"
    result = _validate_only(
        tmp_path,
        "rag",
        prefix=tmp_path / "prefix",
        data_dir=tmp_path / "data",
        generated=tmp_path / "data" / "deploy" / "generated",
        extra_args=[
            "--service-root",
            str(service_root),
            "--install-services",
        ],
        command_log=command_log,
    )
    assert result.returncode != 0
    assert "[fail] role_env_read" in result.stdout
    assert "[pass] rag_preflight" not in result.stdout
    assert "sudo cat" not in read_command_log(command_log)
    assert "ark preflight" not in read_command_log(command_log)


def test_sudo_assisted_real_service_env_passes_validation(tmp_path: Path) -> None:
    install, env, system_root = _run_real_service_root_rag_install(
        tmp_path,
        no_validate=True,
    )
    assert install.returncode == 0, install.stderr
    env_file = system_root / "etc" / "ark-pi" / "ark-rag.env"
    assert env_file.is_file()
    env_file.chmod(0o000)
    command_log = tmp_path / "validate.log"
    env["ARK_PI_INSTALL_COMMAND_LOG"] = str(command_log)
    result = run_install(
        "--role",
        "rag",
        "--validate-only",
        "--install-services",
        "--service-root",
        "/",
        "--prefix",
        "/opt/ark-pi",
        "--data-dir",
        "/srv/ark-pi",
        "--generated-dir",
        "/srv/ark-pi/deploy/generated",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "sudo cat" in log
    assert "ARK_WORKSPACE_DIR=/generated/rag/workspace" in log
    assert "[pass] rag_preflight" in result.stdout


def test_sudo_cat_failure_fails_before_ark_preflight(tmp_path: Path) -> None:
    install, env, system_root = _run_real_service_root_rag_install(
        tmp_path,
        no_validate=True,
    )
    assert install.returncode == 0, install.stderr
    env_file = system_root / "etc" / "ark-pi" / "ark-rag.env"
    env_file.chmod(0o000)
    command_log = tmp_path / "validate.log"
    env["ARK_PI_INSTALL_COMMAND_LOG"] = str(command_log)
    env["ARK_PI_INSTALL_SUDO_CAT_FAIL"] = "1"
    result = run_install(
        "--role",
        "rag",
        "--validate-only",
        "--install-services",
        "--service-root",
        "/",
        "--prefix",
        "/opt/ark-pi",
        "--data-dir",
        "/srv/ark-pi",
        "--generated-dir",
        "/srv/ark-pi/deploy/generated",
        env=env,
    )
    assert result.returncode != 0
    assert "[fail] role_env_read" in result.stdout
    assert "[pass] rag_preflight" not in result.stdout
    assert "ark preflight" not in read_command_log(command_log)


def test_malformed_service_env_via_sudo_fails_before_ark_preflight(tmp_path: Path) -> None:
    install, env, system_root = _run_real_service_root_rag_install(
        tmp_path,
        no_validate=True,
    )
    assert install.returncode == 0, install.stderr
    env_file = system_root / "etc" / "ark-pi" / "ark-rag.env"
    env_file.write_text("not-a-valid-env-line\n", encoding="utf-8")
    env_file.chmod(0o000)
    command_log = tmp_path / "validate.log"
    env["ARK_PI_INSTALL_COMMAND_LOG"] = str(command_log)
    result = run_install(
        "--role",
        "rag",
        "--validate-only",
        "--install-services",
        "--service-root",
        "/",
        "--prefix",
        "/opt/ark-pi",
        "--data-dir",
        "/srv/ark-pi",
        "--generated-dir",
        "/srv/ark-pi/deploy/generated",
        env=env,
    )
    assert result.returncode != 0
    assert "[fail] role_env_parse" in result.stdout
    assert "[pass] rag_preflight" not in result.stdout
    assert "ark preflight" not in read_command_log(command_log)


def test_printed_validation_commands_for_service_install_include_env_loading(
    tmp_path: Path,
) -> None:
    result = _run_service_install(tmp_path, "rag")
    assert result.returncode == 0, result.stderr
    assert "set -a" in result.stdout
    assert "sudo sh -c" not in result.stdout
    service_root = tmp_path / "service-root"
    assert str(service_root / "etc" / "ark-pi" / "ark-rag.env") in result.stdout
    assert "bare ark preflight uses default config" in result.stdout


def test_printed_validation_commands_for_non_service_install_include_generated_env(
    tmp_path: Path,
) -> None:
    result = _run_rag_install(tmp_path)
    assert result.returncode == 0, result.stderr
    generated = tmp_path / "data" / "deploy" / "generated" / "ark-rag.env"
    assert "set -a" in result.stdout
    assert "sudo sh -c" not in result.stdout
    assert str(generated) in result.stdout


def test_printed_validation_commands_for_real_service_root_use_sudo(tmp_path: Path) -> None:
    result, _, _system_root = _run_real_service_root_rag_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "sudo sh -c" in result.stdout
    assert "/etc/ark-pi/ark-rag.env" in result.stdout
    assert "root:root mode 0640" in result.stdout


def test_dry_run_does_not_run_env_aware_validation_commands(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)
    result = run_install(
        "--role",
        "rag",
        "--prefix",
        str(tmp_path / "prefix"),
        "--data-dir",
        str(tmp_path / "data"),
        "--repo",
        "file://fake",
        "--yes",
        "--dry-run",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert read_command_log(command_log) == ""


def _llama_install_env(
    tmp_path: Path,
    prefix: Path,
    *,
    data_dir: Path | None = None,
    command_log: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    data = data_dir or tmp_path / "data"
    llama_bin = data / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server"
    env = fake_helper_env(
        REPO_ROOT,
        extra={
            "ARK_INSTALL_LOCAL_LLAMA_REPO": str(LLAMA_STUB),
            "ARK_PI_INSTALL_LLAMA_BIN": str(llama_bin),
            **(extra_env or {}),
        },
        command_log=command_log,
    )
    return env


def _run_llm_install_with_command_log(
    tmp_path: Path,
    *,
    llama_build: bool = False,
    install_services: bool = False,
    service_root: Path | None = None,
    require_model: bool = False,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    command_log = tmp_path / "commands.log"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = _llama_install_env(tmp_path, prefix, command_log=command_log, extra_env=extra_env)
    args = [
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
    ]
    if llama_build:
        args.append("--llama-build")
    if require_model:
        args.append("--require-model")
    if install_services:
        args.extend(
            [
                "--service-root",
                str(service_root or tmp_path / "service-root"),
                "--install-services",
            ]
        )
    if extra_args:
        args.extend(extra_args)
    result = run_install(*args, env=env)
    return result, command_log, read_command_log(command_log)


def test_llm_dry_run_without_llama_build_omits_llama_apt_packages() -> None:
    result = run_install("--role", "llm", "--dry-run")
    assert result.returncode == 0, result.stderr
    for package in EXPECTED_LLM_APT_PACKAGES:
        assert package not in result.stdout


def test_llm_dry_run_with_llama_build_lists_llama_apt_packages() -> None:
    result = run_install("--role", "llm", "--llama-build", "--dry-run")
    assert result.returncode == 0, result.stderr
    for package in EXPECTED_LLM_APT_PACKAGES:
        assert package in result.stdout
    assert "cmake -S" in result.stdout
    assert " -B " in result.stdout


def test_llm_dry_run_llama_build_shows_cmake_source_dir() -> None:
    result = run_install("--role", "llm", "--llama-build", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "cmake -S" in result.stdout
    assert "/srv/ark-pi/vendor/llama.cpp" in result.stdout
    assert "/opt/ark-pi/vendor" not in result.stdout


def test_llm_dry_run_llama_build_creates_nothing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    command_log = tmp_path / "commands.log"
    env = _llama_install_env(tmp_path, prefix, command_log=command_log)
    result = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--dry-run",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "llama.cpp build steps:" in result.stdout
    assert not prefix.exists()
    assert not data_dir.exists()
    assert read_command_log(command_log) == ""


def test_rag_llama_build_fails_clearly() -> None:
    result = run_install("--role", "rag", "--llama-build", "--dry-run")
    assert result.returncode != 0
    assert "--llama-build requires role llm or both" in result.stderr


def test_cmake_fixture_fails_without_source_dir() -> None:
    cmake = FAKE_BIN / "cmake"
    result = subprocess.run(
        [str(cmake), "-B", str(REPO_ROOT / "tmp-build")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "missing -S" in result.stderr or "CMakeLists.txt" in result.stderr


def test_llm_llama_build_configure_uses_explicit_source_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result, _, log = _run_llm_install_with_command_log(tmp_path, llama_build=True)
    assert result.returncode == 0, result.stderr
    llama_dir = data_dir / "vendor" / "llama.cpp"
    assert f"-S {llama_dir}" in log.replace("\\", "/") or "-S" in log
    assert f"-B {llama_dir / 'build'}" in log.replace("\\", "/") or "-B" in log


def test_llm_llama_build_creates_fake_llama_server_binary(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result, _, log = _run_llm_install_with_command_log(tmp_path, llama_build=True)
    assert result.returncode == 0, result.stderr
    llama_bin = data_dir / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server"
    assert llama_bin.is_file()
    assert llama_bin.stat().st_mode & 0o111
    assert "git clone" in log
    assert "cmake -S" in log
    assert " -B " in log
    assert "cmake --build" in log
    assert f"-S {data_dir / 'vendor' / 'llama.cpp'}" in log.replace("\\", "/") or "-S" in log
    env_content = data_dir / "deploy" / "generated" / "ark-llm.env"
    assert env_content.is_file()
    assert "ARK_LLAMA_BIN=" in env_content.read_text(encoding="utf-8")


def test_both_llama_build_renders_all_templates_and_binary(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = _llama_install_env(tmp_path, prefix)
    result = run_install(
        "--role",
        "both",
        "--llama-build",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    for name in (
        "ark-rag.env",
        "ark-rag.service",
        "ark-llm.env",
        "ark-llm.service",
    ):
        assert (generated / name).is_file()
    llama_bin = data_dir / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server"
    assert llama_bin.is_file()


def test_llm_llama_build_clones_under_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result, _, _ = _run_llm_install_with_command_log(tmp_path, llama_build=True)
    assert result.returncode == 0, result.stderr
    assert (data_dir / "vendor" / "llama.cpp").is_dir()


def test_llm_llama_build_keeps_prefix_clean(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    result, _, _ = _run_llm_install_with_command_log(tmp_path, llama_build=True)
    assert result.returncode == 0, result.stderr
    assert not (prefix / "vendor").exists()


def test_llm_generated_env_uses_data_dir_llama_bin(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result, _, _ = _run_llm_install_with_command_log(tmp_path, llama_build=True)
    assert result.returncode == 0, result.stderr
    llama_bin = data_dir / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server"
    env_text = (data_dir / "deploy" / "generated" / "ark-llm.env").read_text(encoding="utf-8")
    assert f"ARK_LLAMA_BIN={llama_bin}" in env_text


def test_stale_prefix_vendor_dirty_check_is_clear(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    prefix.mkdir()
    (prefix / ".git").mkdir()
    (prefix / "vendor" / "llama.cpp").mkdir(parents=True)
    env = fake_helper_env(REPO_ROOT, {"ARK_INSTALL_GIT_DIRTY": "1"})
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
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert "local changes" in combined
    assert "stale" in combined or "earlier install" in combined
    assert "rm -rf" in combined and "vendor" in combined


def test_custom_llama_dir_under_prefix_still_works(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    custom_llama_dir = prefix / "vendor" / "llama.cpp"
    env = _llama_install_env(
        tmp_path,
        prefix,
        data_dir=data_dir,
        extra_env={"ARK_PI_INSTALL_LLAMA_BIN": str(custom_llama_dir / "build" / "bin" / "llama-server")},
    )
    result = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--llama-dir",
        str(custom_llama_dir),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert custom_llama_dir.is_dir()
    assert (custom_llama_dir / "build" / "bin" / "llama-server").is_file()


def test_llm_custom_paths_reflected_in_generated_templates(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    custom_model = data_dir / "custom" / "weights.gguf"
    env = _llama_install_env(tmp_path, prefix)
    result = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--llama-bin",
        str(prefix / "bin" / "llama-server"),
        "--model-dir",
        str(custom_model.parent),
        "--model-path",
        str(custom_model),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    env_text = (generated / "ark-llm.env").read_text(encoding="utf-8")
    service_text = (generated / "ark-llm.service").read_text(encoding="utf-8")
    assert f"ARK_LLAMA_BIN={prefix / 'bin' / 'llama-server'}" in env_text
    assert f"ARK_MODEL_PATH={custom_model}" in env_text
    assert "ARK_LLAMA_BIN" in service_text


def test_validate_only_llama_build_does_not_run_git_or_cmake(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    command_log = tmp_path / "commands.log"
    env = _llama_install_env(tmp_path, prefix, command_log=command_log)
    install = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    command_log.write_text("", encoding="utf-8")
    result = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(command_log)
    assert "git clone" not in log
    assert "cmake" not in log


def test_require_model_missing_fails_validation(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--require-model",
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode != 0
    assert "[fail] model_file" in result.stdout


def _run_llm_system_root_service_install(
    tmp_path: Path,
    *,
    llama_build: bool = False,
    require_model: bool = False,
    no_start: bool = False,
    systemctl_inactive: bool = False,
    command_log: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    log_path = command_log or tmp_path / "commands.log"
    prefix = tmp_path / "system-root" / "opt" / "ark-pi"
    data_dir = tmp_path / "system-root" / "srv" / "ark-pi"
    extra_env: dict[str, str] = {
        "ARK_INSTALL_LOCAL_LLAMA_REPO": str(LLAMA_STUB),
        "ARK_PI_INSTALL_LLAMA_BIN": str(
            data_dir / "vendor" / "llama.cpp" / "build" / "bin" / "llama-server"
        ),
    }
    if systemctl_inactive:
        extra_env["ARK_PI_INSTALL_SYSTEMCTL_INACTIVE"] = "1"
    env, _system_root = fake_system_root_env(
        tmp_path,
        REPO_ROOT,
        command_log=log_path,
        extra=extra_env,
    )
    args = [
        "--role",
        "llm",
        "--no-os-packages",
        "--install-services",
        "--yes",
        "--repo",
        "file://fake",
    ]
    if llama_build:
        args.append("--llama-build")
    if require_model:
        args.append("--require-model")
    if no_start:
        args.append("--no-start")
    result = run_install(*args, env=env)
    return result, log_path, read_command_log(log_path)


def test_llm_service_install_missing_model_skips_systemctl_start(tmp_path: Path) -> None:
    result, _, log = _run_llm_system_root_service_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "systemctl enable ark-llm.service" in log
    assert "systemctl start ark-llm.service" not in log
    assert "Skipping systemctl start for ark-llm.service" in result.stdout


def test_llm_service_install_require_model_missing_fails_before_start(tmp_path: Path) -> None:
    result, _, log = _run_llm_system_root_service_install(tmp_path, require_model=True)
    assert result.returncode != 0
    assert "model file required" in result.stderr.lower()
    assert "systemctl start ark-llm.service" not in log


def test_env_allowlist_accepts_ark_llama_bin(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "[pass] llm_preflight" in result.stdout
    assert "role_env_unknown_keys" not in result.stdout


def test_llm_post_install_output_uses_llm_env_not_rag(tmp_path: Path) -> None:
    result, _, _ = _run_llm_install_with_command_log(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "One-liner example (llm):" in result.stdout
    assert "One-liner example (rag):" not in result.stdout
    assert "ark-llm.env" in result.stdout
    assert "Role env (llm):" in result.stdout


def test_llm_post_install_output_omits_rag_curl_checks(tmp_path: Path) -> None:
    result, _, _ = _run_llm_install_with_command_log(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "curl http://127.0.0.1:8000/healthz" not in result.stdout
    assert "curl http://127.0.0.1:8000/api/status" not in result.stdout
    assert "LLM service checks:" in result.stdout
    assert "systemctl status ark-llm.service" in result.stdout


def test_both_post_install_output_includes_rag_and_llm_hints(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    env = _llama_install_env(tmp_path, prefix)
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
    assert "One-liner example (rag):" in result.stdout
    assert "One-liner example (llm):" in result.stdout
    assert "RAG API checks:" in result.stdout
    assert "curl http://127.0.0.1:8000/healthz" in result.stdout
    assert "LLM service checks:" in result.stdout
    assert "systemctl status ark-llm.service" in result.stdout


def test_llm_no_start_missing_model_passes_with_warnings(tmp_path: Path) -> None:
    result, _, log = _run_llm_system_root_service_install(
        tmp_path,
        no_start=True,
        systemctl_inactive=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Validation: PASS (with warnings)" in result.stdout
    assert "[warning] model_file" in result.stdout
    assert "[pass] systemctl_enabled" in result.stdout
    assert "not active (--no-start; expected)" in result.stdout
    assert "systemctl start ark-llm.service" not in log


def test_legacy_llamacpp_env_accepted_by_validation(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    service_root = tmp_path / "service-root"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--service-root",
        str(service_root),
        "--install-services",
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    _write_env(service_root / "etc" / "ark-pi" / "ark-llm.env", LEGACY_LLM_SERVICE_ENV)
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--service-root",
        str(service_root),
        "--install-services",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "[pass] llm_preflight" in result.stdout
    assert "role_env_unknown_keys" not in result.stdout


TINY_CUSTOM_DOWNLOAD_ARGS = [
    "--download-model",
    "--model-preset",
    "custom",
    "--model-url",
    "https://example.invalid/models/tiny-q4km.gguf",
    "--model-sha256",
    TINY_MODEL_SHA,
]


def _model_download_install_env(
    tmp_path: Path,
    prefix: Path,
    *,
    data_dir: Path | None = None,
    curl_source: Path | None = None,
    command_log: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = fake_helper_env(
        REPO_ROOT,
        extra={
            "ARK_PI_INSTALL_CURL_SOURCE": str(curl_source or TINY_MODEL),
            **(extra_env or {}),
        },
        command_log=command_log,
    )
    return env


def _run_model_download_install(
    tmp_path: Path,
    *,
    install_services: bool = False,
    service_root: Path | None = None,
    no_start: bool = False,
    require_model: bool = False,
    curl_source: Path | None = None,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, str]:
    command_log = tmp_path / "commands.log"
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = _model_download_install_env(
        tmp_path,
        prefix,
        data_dir=data_dir,
        curl_source=curl_source,
        command_log=command_log,
        extra_env=extra_env,
    )
    args = [
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        *TINY_CUSTOM_DOWNLOAD_ARGS,
    ]
    if install_services:
        args.extend(
            [
                "--service-root",
                str(service_root or tmp_path / "service-root"),
                "--install-services",
            ]
        )
    if no_start:
        args.append("--no-start")
    if require_model:
        args.append("--require-model")
    if extra_args:
        args.extend(extra_args)
    result = run_install(*args, env=env)
    return result, prefix, data_dir, command_log, read_command_log(command_log)


def test_llm_dry_run_download_model_prints_default_preset() -> None:
    result = run_install("--role", "llm", "--download-model", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "qwen3-4b-q4km" in result.stdout
    assert "Qwen3 4B Q4_K_M" in result.stdout
    assert "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5" in result.stdout
    assert "Dry run: no download will occur." in result.stdout


def test_llm_dry_run_download_model_8b_preset_shows_advanced_note() -> None:
    result = run_install(
        "--role",
        "llm",
        "--download-model",
        "--model-preset",
        "qwen3-8b-q4km",
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    assert "qwen3-8b-q4km" in result.stdout
    assert "Qwen3 8B Q4_K_M" in result.stdout
    assert "609eb8a9fb256d0e2be8b8d252b00bae7c0496fac5e9ccca190206abbb24e2e5" in result.stdout
    assert "advanced preset" in result.stdout


def test_rag_download_model_fails() -> None:
    result = run_install("--role", "rag", "--download-model", "--dry-run")
    assert result.returncode != 0
    assert "--download-model requires role llm or both" in result.stderr


def test_llm_dry_run_download_model_never_runs_curl(tmp_path: Path) -> None:
    command_log = tmp_path / "commands.log"
    env = fake_helper_env(REPO_ROOT, command_log=command_log)
    result = run_install(
        "--role",
        "llm",
        "--download-model",
        "--dry-run",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "curl" not in read_command_log(command_log)


def test_llm_download_installs_model_atomically(tmp_path: Path) -> None:
    result, _, data_dir, _, log = _run_model_download_install(tmp_path)
    assert result.returncode == 0, result.stderr
    model_path = data_dir / "models" / "model.gguf"
    assert model_path.is_file()
    assert model_path.read_bytes() == TINY_MODEL.read_bytes()
    assert "curl" in log
    assert "curl -fL" in log
    assert not list((data_dir / "models").glob("model.gguf.tmp.*"))


def test_llm_download_checksum_mismatch_leaves_no_final_model(tmp_path: Path) -> None:
    result, _, data_dir, _, _ = _run_model_download_install(
        tmp_path,
        curl_source=TINY_WRONG_MODEL,
    )
    assert result.returncode != 0
    assert (data_dir / "models" / "model.gguf").exists() is False
    assert "SHA256 mismatch" in result.stderr or "failed SHA256 verification" in result.stderr


def test_llm_download_skips_when_existing_model_matches(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "model.gguf"
    shutil.copy(TINY_MODEL, model_path)
    result, _, _, _, log = _run_model_download_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "skipping download" in result.stdout.lower()
    assert "curl -fL" not in log


def test_llm_download_existing_invalid_model_fails_without_force(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "model.gguf"
    shutil.copy(TINY_WRONG_MODEL, model_path)
    result, _, _, _, log = _run_model_download_install(tmp_path)
    assert result.returncode != 0
    assert "does not match expected checksum" in result.stderr.lower()
    assert model_path.read_bytes() == TINY_WRONG_MODEL.read_bytes()
    assert "curl -fL" not in log


def test_llm_download_force_replaces_existing_model_after_verify(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "model.gguf"
    shutil.copy(TINY_WRONG_MODEL, model_path)
    result, _, _, _, log = _run_model_download_install(
        tmp_path,
        extra_args=["--force-model-download"],
    )
    assert result.returncode == 0, result.stderr
    assert model_path.read_bytes() == TINY_MODEL.read_bytes()
    assert "curl" in log
    assert "curl -fL" in log


def test_llm_validate_only_never_runs_curl(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    command_log = tmp_path / "commands.log"
    env = _model_download_install_env(tmp_path, prefix, command_log=command_log)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--model-preset",
        "qwen3-4b-q4km",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "curl -fL" not in read_command_log(command_log)


def test_llm_custom_preset_without_sha256_fails() -> None:
    result = run_install(
        "--role",
        "llm",
        "--download-model",
        "--model-preset",
        "custom",
        "--model-url",
        "https://example.invalid/model.gguf",
        "--dry-run",
    )
    assert result.returncode != 0
    assert "requires --model-sha256" in result.stderr


def test_llm_custom_preset_with_url_and_sha256_downloads(tmp_path: Path) -> None:
    result, _, data_dir, _, _ = _run_model_download_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (data_dir / "models" / "model.gguf").is_file()


def test_llm_validate_model_file_passes_when_present(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True)
    shutil.copy(TINY_MODEL, model_dir / "model.gguf")
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--model-sha256",
        TINY_MODEL_SHA,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "[pass] model_file" in result.stdout
    assert "[pass] model_sha256" in result.stdout


def test_llm_validate_model_file_warns_when_missing(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "[warning] model_file" in result.stdout


def test_llm_validate_model_sha256_fails_on_mismatch(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    data_dir = tmp_path / "data"
    generated = data_dir / "deploy" / "generated"
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True)
    shutil.copy(TINY_WRONG_MODEL, model_dir / "model.gguf")
    env = fake_helper_env(REPO_ROOT)
    install = run_install(
        "--role",
        "llm",
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        "--repo",
        "file://fake",
        "--yes",
        env=env,
    )
    assert install.returncode == 0, install.stderr
    result = run_install(
        "--role",
        "llm",
        "--validate-only",
        "--model-sha256",
        TINY_MODEL_SHA,
        "--prefix",
        str(prefix),
        "--data-dir",
        str(data_dir),
        "--generated-dir",
        str(generated),
        env=env,
    )
    assert result.returncode != 0
    assert "[fail] model_sha256" in result.stdout


def test_llm_service_start_proceeds_when_model_present(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.log"
    system_root = tmp_path / "system-root"
    (system_root / "opt").mkdir(parents=True)
    model_dir = system_root / "srv" / "ark-pi" / "models"
    model_dir.mkdir(parents=True)
    shutil.copy(TINY_MODEL, model_dir / "model.gguf")
    (system_root / "opt").chmod(0o555)
    (system_root / "srv").chmod(0o555)
    extra_env: dict[str, str] = {
        "ARK_INSTALL_LOCAL_LLAMA_REPO": str(LLAMA_STUB),
        "ARK_PI_INSTALL_LLAMA_BIN": str(
            system_root
            / "srv"
            / "ark-pi"
            / "vendor"
            / "llama.cpp"
            / "build"
            / "bin"
            / "llama-server"
        ),
        "ARK_PI_INSTALL_CURL_SOURCE": str(TINY_MODEL),
        "ARK_PI_INSTALL_TEST_SYSTEM_ROOT": str(system_root),
    }
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=log_path)
    result = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--no-os-packages",
        "--install-services",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(log_path)
    assert "systemctl start ark-llm.service" in log


def test_llm_download_without_llama_build_skips_systemctl_start(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.log"
    system_root = tmp_path / "system-root"
    (system_root / "opt").mkdir(parents=True)
    (system_root / "srv").mkdir(parents=True)
    (system_root / "opt").chmod(0o555)
    (system_root / "srv").chmod(0o555)
    extra_env: dict[str, str] = {
        "ARK_PI_INSTALL_CURL_SOURCE": str(TINY_MODEL),
        "ARK_PI_INSTALL_TEST_SYSTEM_ROOT": str(system_root),
    }
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=log_path)
    result = run_install(
        "--role",
        "llm",
        "--no-os-packages",
        "--install-services",
        "--yes",
        "--repo",
        "file://fake",
        *TINY_CUSTOM_DOWNLOAD_ARGS,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (system_root / "srv" / "ark-pi" / "models" / "model.gguf").is_file()
    log = read_command_log(log_path)
    assert "systemctl start ark-llm.service" not in log
    assert "llama-server binary missing" in result.stdout


def test_llm_no_start_skips_even_with_model_and_binary(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.log"
    system_root = tmp_path / "system-root"
    (system_root / "opt").mkdir(parents=True)
    model_dir = system_root / "srv" / "ark-pi" / "models"
    model_dir.mkdir(parents=True)
    shutil.copy(TINY_MODEL, model_dir / "model.gguf")
    (system_root / "opt").chmod(0o555)
    (system_root / "srv").chmod(0o555)
    extra_env: dict[str, str] = {
        "ARK_INSTALL_LOCAL_LLAMA_REPO": str(LLAMA_STUB),
        "ARK_PI_INSTALL_LLAMA_BIN": str(
            system_root
            / "srv"
            / "ark-pi"
            / "vendor"
            / "llama.cpp"
            / "build"
            / "bin"
            / "llama-server"
        ),
        "ARK_PI_INSTALL_TEST_SYSTEM_ROOT": str(system_root),
    }
    env = fake_helper_env(REPO_ROOT, extra=extra_env, command_log=log_path)
    result = run_install(
        "--role",
        "llm",
        "--llama-build",
        "--no-os-packages",
        "--install-services",
        "--no-start",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(log_path)
    assert "systemctl start ark-llm.service" not in log


def test_rag_service_start_unchanged_when_llm_prerequisites_missing(tmp_path: Path) -> None:
    log_path = tmp_path / "commands.log"
    env, _ = fake_system_root_env(tmp_path, REPO_ROOT, command_log=log_path)
    result = run_install(
        "--role",
        "rag",
        "--no-os-packages",
        "--install-services",
        "--yes",
        "--repo",
        "file://fake",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    log = read_command_log(log_path)
    assert "systemctl start ark-rag.service" in log
    assert "systemctl start ark-llm.service" not in log


def test_llm_download_writes_model_under_data_dir_not_prefix(tmp_path: Path) -> None:
    result, prefix, data_dir, _, _ = _run_model_download_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (data_dir / "models" / "model.gguf").is_file()
    assert not (prefix / "models").exists()
