import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from ark_pi.deploy.bundle import build_deployment_bundle
from ark_pi.deploy.bundle_verify import verify_deployment_bundle
from ark_pi.deploy.templates import render_deployment_templates


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


@pytest.fixture
def valid_all_bundle(rendered_dir: Path, tmp_path: Path) -> Path:
    output = tmp_path / "bundle-all.zip"
    build_deployment_bundle(rendered_dir, output_path=output, role="all", force=True)
    return output


@pytest.fixture
def valid_rag_bundle(rendered_dir: Path, tmp_path: Path) -> Path:
    output = tmp_path / "bundle-rag.zip"
    build_deployment_bundle(rendered_dir, output_path=output, role="rag", force=True)
    return output


@pytest.fixture
def valid_llm_bundle(rendered_dir: Path, tmp_path: Path) -> Path:
    output = tmp_path / "bundle-llm.zip"
    build_deployment_bundle(rendered_dir, output_path=output, role="llm", force=True)
    return output


def _read_zip_files(bundle_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(bundle_path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _write_zip_files(output: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)


def _patch_bundle(
    source: Path,
    dest: Path,
    patch: Callable[[dict[str, bytes]], None],
) -> Path:
    files = _read_zip_files(source)
    patch(files)
    _write_zip_files(dest, files)
    return dest


def test_verify_valid_all_role_bundle_succeeds(valid_all_bundle: Path) -> None:
    result = verify_deployment_bundle(valid_all_bundle)

    assert result.overall_status == "valid"
    assert result.role == "all"
    assert result.entry_count == 9
    assert result.manifest_entry_count == 8
    assert result.host_mutations_performed is False
    assert result.network_checks_performed is False
    assert all(check.status == "pass" for check in result.checks)


def test_verify_valid_rag_bundle_succeeds_and_has_no_llm_templates(
    valid_rag_bundle: Path,
) -> None:
    result = verify_deployment_bundle(valid_rag_bundle)

    assert result.overall_status == "valid"
    assert result.role == "rag"
    template_check = next(check for check in result.checks if check.id == "template_sanity")
    assert template_check.status == "pass"
    expected_check = next(check for check in result.checks if check.id == "expected_entries")
    assert expected_check.status == "pass"


def test_verify_valid_llm_bundle_succeeds_and_has_no_rag_templates(
    valid_llm_bundle: Path,
) -> None:
    result = verify_deployment_bundle(valid_llm_bundle)

    assert result.overall_status == "valid"
    assert result.role == "llm"
    template_check = next(check for check in result.checks if check.id == "template_sanity")
    assert template_check.status == "pass"


def test_missing_bundle_path_returns_invalid(tmp_path: Path) -> None:
    missing = tmp_path / "missing.zip"
    result = verify_deployment_bundle(missing)

    assert result.overall_status == "invalid"
    zip_check = next(check for check in result.checks if check.id == "zip_open")
    assert zip_check.status == "fail"


def test_invalid_zip_returns_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    result = verify_deployment_bundle(bad)

    assert result.overall_status == "invalid"
    zip_check = next(check for check in result.checks if check.id == "zip_open")
    assert zip_check.status == "fail"


def test_missing_manifest_returns_invalid(valid_all_bundle: Path, tmp_path: Path) -> None:
    patched = _patch_bundle(
        valid_all_bundle,
        tmp_path / "no-manifest.zip",
        lambda files: files.pop("manifest.json"),
    )
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    manifest_check = next(check for check in result.checks if check.id == "manifest_present")
    assert manifest_check.status == "fail"


def test_unsupported_manifest_schema_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["schema_version"] = 99
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

    patched = _patch_bundle(valid_all_bundle, tmp_path / "bad-schema.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    schema_check = next(check for check in result.checks if check.id == "manifest_schema")
    assert schema_check.status == "fail"


def test_dry_run_false_in_manifest_returns_invalid(valid_all_bundle: Path, tmp_path: Path) -> None:
    def patch(files: dict[str, bytes]) -> None:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["dry_run"] = False
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

    patched = _patch_bundle(valid_all_bundle, tmp_path / "not-dry-run.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    safety_check = next(check for check in result.checks if check.id == "safety_flags")
    assert safety_check.status == "fail"


def test_host_mutations_performed_true_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["host_mutations_performed"] = True
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

    patched = _patch_bundle(valid_all_bundle, tmp_path / "host-mutations.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    safety_check = next(check for check in result.checks if check.id == "safety_flags")
    assert safety_check.status == "fail"


def test_network_checks_performed_true_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        manifest["network_checks_performed"] = True
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")

    patched = _patch_bundle(valid_all_bundle, tmp_path / "network-checks.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    safety_check = next(check for check in result.checks if check.id == "safety_flags")
    assert safety_check.status == "fail"


def test_checksum_mismatch_returns_invalid(valid_all_bundle: Path, tmp_path: Path) -> None:
    def patch(files: dict[str, bytes]) -> None:
        files["README.txt"] = b"tampered readme\n"

    patched = _patch_bundle(valid_all_bundle, tmp_path / "checksum-mismatch.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    checksum_check = next(check for check in result.checks if check.id == "checksums")
    assert checksum_check.status == "fail"


def test_extra_forbidden_entry_returns_invalid(valid_all_bundle: Path, tmp_path: Path) -> None:
    def patch(files: dict[str, bytes]) -> None:
        files["data/secret.txt"] = b"secret\n"

    patched = _patch_bundle(valid_all_bundle, tmp_path / "forbidden-entry.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    forbidden_check = next(check for check in result.checks if check.id == "forbidden_entries")
    assert forbidden_check.status == "fail"


def test_traversal_entry_returns_invalid(valid_all_bundle: Path, tmp_path: Path) -> None:
    def patch(files: dict[str, bytes]) -> None:
        files["../etc/passwd"] = b"root\n"

    patched = _patch_bundle(valid_all_bundle, tmp_path / "traversal.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    forbidden_check = next(check for check in result.checks if check.id == "forbidden_entries")
    assert forbidden_check.status == "fail"


def test_invalid_deployment_plan_json_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        files["reports/deployment-plan.json"] = b"{not json"

    patched = _patch_bundle(valid_all_bundle, tmp_path / "bad-plan-json.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    report_check = next(check for check in result.checks if check.id == "report_json")
    assert report_check.status == "fail"


def test_plan_copy_step_performed_true_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        plan = json.loads(files["reports/deployment-plan.json"].decode("utf-8"))
        plan["copy_steps"][0]["performed"] = True
        files["reports/deployment-plan.json"] = (json.dumps(plan, indent=2) + "\n").encode(
            "utf-8"
        )

    patched = _patch_bundle(valid_all_bundle, tmp_path / "performed-copy.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    plan_check = next(check for check in result.checks if check.id == "plan_safety")
    assert plan_check.status == "fail"


def test_plan_manual_command_performed_true_returns_invalid(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    def patch(files: dict[str, bytes]) -> None:
        plan = json.loads(files["reports/deployment-plan.json"].decode("utf-8"))
        plan["manual_commands"][0]["performed"] = True
        files["reports/deployment-plan.json"] = (json.dumps(plan, indent=2) + "\n").encode(
            "utf-8"
        )

    patched = _patch_bundle(valid_all_bundle, tmp_path / "performed-command.zip", patch)
    result = verify_deployment_bundle(patched)

    assert result.overall_status == "invalid"
    plan_check = next(check for check in result.checks if check.id == "plan_safety")
    assert plan_check.status == "fail"
