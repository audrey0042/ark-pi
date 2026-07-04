"""Subprocess tests for install.sh planner, app bootstrap, and deploy render."""

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


def fake_helper_env(
    local_repo: Path,
    extra: dict[str, str] | None = None,
    render_log: Path | None = None,
) -> dict[str, str]:
    env = {
        "PATH": f"{FAKE_BIN}:{os.environ.get('PATH', '')}",
        "ARK_INSTALL_LOCAL_REPO": str(local_repo),
    }
    if render_log is not None:
        env["ARK_INSTALL_RENDER_LOG"] = str(render_log)
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
    assert "--generated-dir" in result.stdout
    assert "--install-services" in result.stdout
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
