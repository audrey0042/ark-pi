import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from ark_pi.deploy.bundle import build_deployment_bundle
from ark_pi.deploy.bundle_unpack import unpack_deployment_bundle, validate_staging_dir
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


def test_unpack_valid_all_role_bundle_succeeds(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    result = unpack_deployment_bundle(valid_all_bundle, staging_dir=staging, force=True)

    assert result.verification_status in {"valid", "warning"}
    assert result.role == "all"
    assert result.extracted_count == 9
    assert (staging / "README.txt").is_file()
    assert (staging / "manifest.json").is_file()
    assert (staging / "templates" / "ark-rag.env").is_file()
    assert (staging / "reports" / "deployment-plan.json").is_file()


def test_unpack_creates_expected_layout(valid_all_bundle: Path, tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    unpack_deployment_bundle(valid_all_bundle, staging_dir=staging, force=True)

    expected_files = {
        "README.txt",
        "manifest.json",
        "reports/deployment-preflight.json",
        "reports/deployment-plan.json",
        "reports/deployment-plan.md",
        "templates/ark-rag.env",
        "templates/ark-rag.service",
        "templates/ark-llm.env",
        "templates/ark-llm.service",
    }
    extracted = {
        str(path.relative_to(staging))
        for path in staging.rglob("*")
        if path.is_file()
    }
    assert extracted == expected_files


def test_unpack_valid_rag_bundle_excludes_llm_templates(
    valid_rag_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging-rag"
    result = unpack_deployment_bundle(valid_rag_bundle, staging_dir=staging, force=True)

    assert result.role == "rag"
    assert (staging / "templates" / "ark-rag.env").is_file()
    assert not (staging / "templates" / "ark-llm.env").exists()
    assert not (staging / "templates" / "ark-llm.service").exists()


def test_unpack_valid_llm_bundle_excludes_rag_templates(
    valid_llm_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging-llm"
    result = unpack_deployment_bundle(valid_llm_bundle, staging_dir=staging, force=True)

    assert result.role == "llm"
    assert (staging / "templates" / "ark-llm.env").is_file()
    assert not (staging / "templates" / "ark-rag.env").exists()
    assert not (staging / "templates" / "ark-rag.service").exists()


def test_invalid_bundle_fails_and_extracts_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(ValueError, match="verification is invalid"):
        unpack_deployment_bundle(bad, staging_dir=staging, force=True)

    assert not any(staging.iterdir())


def test_tampered_checksum_bundle_fails_and_extracts_nothing(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    tampered = _patch_bundle(
        valid_all_bundle,
        tmp_path / "tampered.zip",
        lambda files: files.update({"README.txt": b"tampered\n"}),
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(ValueError, match="verification is invalid"):
        unpack_deployment_bundle(tampered, staging_dir=staging, force=True)

    assert not any(staging.iterdir())


def test_traversal_entry_bundle_fails_and_extracts_nothing(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    traversal = _patch_bundle(
        valid_all_bundle,
        tmp_path / "traversal.zip",
        lambda files: files.update({"../etc/passwd": b"root\n"}),
    )
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(ValueError, match="verification is invalid"):
        unpack_deployment_bundle(traversal, staging_dir=staging, force=True)

    assert not any(staging.iterdir())


def test_non_empty_staging_without_force_fails(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty staging directory"):
        unpack_deployment_bundle(valid_all_bundle, staging_dir=staging)

    assert (staging / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_non_empty_staging_with_force_succeeds_and_clears_staging_only(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = root / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    staging = root / "staging"
    staging.mkdir()
    (staging / "old.txt").write_text("old", encoding="utf-8")

    unpack_deployment_bundle(valid_all_bundle, staging_dir=staging, force=True)

    assert outside.read_text(encoding="utf-8") == "outside"
    assert not (staging / "old.txt").exists()
    assert (staging / "README.txt").is_file()


def test_forbidden_staging_dir_under_etc_is_rejected() -> None:
    with pytest.raises(ValueError, match="Refusing to unpack into forbidden staging directory"):
        validate_staging_dir(Path("/etc/ark-pi-staging"))


def test_no_files_written_outside_staging_dir(
    valid_all_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    staging = root / "staging"
    before = {path for path in root.rglob("*")}

    unpack_deployment_bundle(valid_all_bundle, staging_dir=staging, force=True)

    after = {path for path in root.rglob("*")}
    new_paths = after - before
    assert new_paths
    assert all(path.resolve().is_relative_to(staging.resolve()) for path in new_paths)
