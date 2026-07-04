import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ark_pi.deploy.bundle import (
    BUNDLE_SCHEMA_VERSION,
    build_deployment_bundle,
    validate_bundle_output_path,
)
from ark_pi.deploy.templates import render_deployment_templates


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


def _zip_names(bundle_path: Path) -> set[str]:
    with zipfile.ZipFile(bundle_path) as archive:
        return set(archive.namelist())


def test_build_bundle_all_writes_zip(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-all.zip"
    result = build_deployment_bundle(
        rendered_dir,
        output_path=output,
        role="all",
        force=True,
    )

    assert output.is_file()
    assert result.output_path == str(output.resolve())
    assert result.role == "all"
    assert result.entry_count == 9
    assert result.preflight_overall_status in {"ready", "warning"}
    assert result.bundle_size_bytes == output.stat().st_size


def test_bundle_all_includes_expected_entries(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-all.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    names = _zip_names(output)
    assert names == {
        "manifest.json",
        "README.txt",
        "reports/deployment-plan.json",
        "reports/deployment-plan.md",
        "reports/deployment-preflight.json",
        "templates/ark-llm.env",
        "templates/ark-llm.service",
        "templates/ark-rag.env",
        "templates/ark-rag.service",
    }


def test_bundle_rag_includes_only_rag_templates(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-rag.zip"
    build_deployment_bundle(rendered_dir, output_path=output, role="rag", force=True)

    names = _zip_names(output)
    assert "templates/ark-rag.env" in names
    assert "templates/ark-rag.service" in names
    assert "templates/ark-llm.env" not in names
    assert "templates/ark-llm.service" not in names
    assert "reports/deployment-preflight.json" in names
    assert "manifest.json" in names
    assert "README.txt" in names


def test_bundle_llm_includes_only_llm_templates(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle-llm.zip"
    build_deployment_bundle(rendered_dir, output_path=output, role="llm", force=True)

    names = _zip_names(output)
    assert "templates/ark-llm.env" in names
    assert "templates/ark-llm.service" in names
    assert "templates/ark-rag.env" not in names
    assert "templates/ark-rag.service" not in names


def test_manifest_schema_version_is_one(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["schema_version"] == BUNDLE_SCHEMA_VERSION


def test_manifest_dry_run_flags(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["dry_run"] is True
    assert manifest["host_mutations_performed"] is False
    assert manifest["network_checks_performed"] is False


def test_manifest_entries_include_sha256_checksums(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["entries"]
    for entry in manifest["entries"]:
        assert entry["path"]
        assert entry["size_bytes"] > 0
        assert len(entry["sha256"]) == 64


def test_checksums_match_zip_entry_contents(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    with zipfile.ZipFile(output) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        for entry in manifest["entries"]:
            content = archive.read(entry["path"])
            assert len(content) == entry["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_existing_output_without_force_fails(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    output.write_bytes(b"existing")

    with pytest.raises(ValueError, match="Refusing to overwrite"):
        build_deployment_bundle(rendered_dir, output_path=output)


def test_existing_output_with_force_succeeds(rendered_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "bundle.zip"
    output.write_bytes(b"existing")

    build_deployment_bundle(rendered_dir, output_path=output, force=True)

    with zipfile.ZipFile(output) as archive:
        assert "manifest.json" in archive.namelist()


def test_output_path_under_etc_is_rejected() -> None:
    with pytest.raises(ValueError, match="Refusing to write bundle output under /etc"):
        validate_bundle_output_path(Path("/etc/ark-pi-bundle.zip"))


def test_missing_generated_templates_fails_clearly(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"
    output = tmp_path / "bundle.zip"

    with pytest.raises(ValueError, match="deployment preflight is blocked"):
        build_deployment_bundle(missing, output_path=output, force=True)
