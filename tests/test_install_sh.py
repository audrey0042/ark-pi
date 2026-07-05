"""Subprocess tests for install.sh planner, app bootstrap, and deploy render."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
FAKE_BIN = REPO_ROOT / "tests" / "fixtures" / "install_helpers"

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
    assert env_file.read_text(encoding="utf-8") == "ARK_ROLE=rag\n"
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
    assert existing.read_text(encoding="utf-8") == "ARK_ROLE=rag\n"
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
    assert "[warning] llm_model_file" in result.stdout
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
