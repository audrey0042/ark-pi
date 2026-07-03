from pathlib import Path

import pytest
from typer.testing import CliRunner

from ark_pi.cli import app
from ark_pi.config import clear_settings_cache
from ark_pi.workspace import catalog as workspace_catalog
from ark_pi.workspace.paths import index_root_dir

runner = CliRunner()


@pytest.fixture
def workspace_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source_dir = tmp_path / "sources"
    workspace_dir = tmp_path / "workspace"
    source_dir.mkdir()
    monkeypatch.setenv("ARK_SOURCE_DIR", str(source_dir))
    monkeypatch.setenv("ARK_WORKSPACE_DIR", str(workspace_dir))
    clear_settings_cache()
    yield workspace_dir, source_dir
    clear_settings_cache()


def _env(workspace_dir: Path, source_dir: Path) -> dict[str, str]:
    return {
        "ARK_WORKSPACE_DIR": str(workspace_dir),
        "ARK_SOURCE_DIR": str(source_dir),
    }


def _ingest_sample(workspace_dir: Path, source_dir: Path, *, index_name: str) -> str:
    (source_dir / "sample.txt").write_text(
        "Ark Pi workspace CLI management test content.\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "workspace",
            "ingest-path",
            "--source",
            "sample.txt",
            "--index-name",
            index_name,
        ],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    entry = workspace_catalog.get_index(workspace_dir, index_name)
    assert entry is not None
    return entry.slug


def test_workspace_list_empty_exits_zero(workspace_env: tuple[Path, Path]) -> None:
    workspace_dir, source_dir = workspace_env
    result = runner.invoke(
        app,
        ["workspace", "list"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert "No workspace indexes found" in result.stdout


def test_workspace_list_shows_created_index(workspace_env: tuple[Path, Path]) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")

    result = runner.invoke(
        app,
        ["workspace", "list"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert "local-sample" in result.stdout
    assert slug in result.stdout
    assert "Workspace Indexes" in result.stdout


def test_workspace_show_displays_expected_fields(workspace_env: tuple[Path, Path]) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")

    result = runner.invoke(
        app,
        ["workspace", "show", "--slug", slug],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert "local-sample" in result.stdout
    assert "chunk_count" in result.stdout
    assert "source_count" in result.stdout
    assert "chunks_path" in result.stdout
    assert "index_dir" in result.stdout
    assert "created_at" in result.stdout
    assert "updated_at" in result.stdout


def test_workspace_show_missing_slug_exits_nonzero(
    workspace_env: tuple[Path, Path],
) -> None:
    workspace_dir, source_dir = workspace_env
    result = runner.invoke(
        app,
        ["workspace", "show", "--slug", "missing"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert "not found" in result.stderr or "not found" in result.stdout


def test_workspace_delete_without_yes_refuses(
    workspace_env: tuple[Path, Path],
) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")

    result = runner.invoke(
        app,
        ["workspace", "delete", "--slug", slug],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert "--yes" in result.stderr or "--yes" in result.stdout
    assert workspace_catalog.get_index(workspace_dir, slug) is not None
    assert index_root_dir(workspace_dir, slug).is_dir()


def test_workspace_delete_with_yes_removes_index(
    workspace_env: tuple[Path, Path],
) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")

    result = runner.invoke(
        app,
        ["workspace", "delete", "--slug", slug, "--yes"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert "Deleted workspace index" in result.stdout or slug in result.stdout
    assert workspace_catalog.get_index(workspace_dir, slug) is None
    assert not index_root_dir(workspace_dir, slug).exists()


def test_workspace_delete_one_index_leaves_other(
    workspace_env: tuple[Path, Path],
) -> None:
    workspace_dir, source_dir = workspace_env
    slug_a = _ingest_sample(workspace_dir, source_dir, index_name="alpha")
    (source_dir / "beta.txt").write_text("Beta content.\n", encoding="utf-8")
    slug_b = _ingest_sample(workspace_dir, source_dir, index_name="beta")

    result = runner.invoke(
        app,
        ["workspace", "delete", "--slug", slug_a, "--yes"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert workspace_catalog.get_index(workspace_dir, slug_a) is None
    assert workspace_catalog.get_index(workspace_dir, slug_b) is not None
    assert index_root_dir(workspace_dir, slug_b).is_dir()


def test_workspace_delete_traversal_slug_exits_nonzero(
    workspace_env: tuple[Path, Path],
) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")

    result = runner.invoke(
        app,
        ["workspace", "delete", "--slug", "../escape", "--yes"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert workspace_catalog.get_index(workspace_dir, slug) is not None


def test_workspace_ingest_path_help() -> None:
    result = runner.invoke(app, ["workspace", "ingest-path", "--help"])
    assert result.exit_code == 0
    assert "--source" in result.stdout
    assert "--index-name" in result.stdout


def test_workspace_ingest_path_happy_path(workspace_env: tuple[Path, Path]) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    assert (workspace_dir / "catalog.json").is_file()


def test_workspace_ingest_path_outside_source_dir_exits_nonzero(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    outside = tmp_path / "outside.txt"
    outside.write_text("Outside content.", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "workspace",
            "ingest-path",
            "--source",
            str(outside),
            "--index-name",
            "bad",
        ],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert "inside configured source_dir" in result.stderr or "inside configured source_dir" in result.stdout


def test_workspace_list_help() -> None:
    result = runner.invoke(app, ["workspace", "list", "--help"])
    assert result.exit_code == 0


def test_workspace_show_help() -> None:
    result = runner.invoke(app, ["workspace", "show", "--help"])
    assert result.exit_code == 0
    assert "--slug" in result.stdout


def test_workspace_delete_help() -> None:
    result = runner.invoke(app, ["workspace", "delete", "--help"])
    assert result.exit_code == 0
    assert "--slug" in result.stdout
    assert "--yes" in result.stdout


def test_workspace_export_help() -> None:
    result = runner.invoke(app, ["workspace", "export", "--help"])
    assert result.exit_code == 0
    assert "--output" in result.stdout
    assert "--slug" in result.stdout
    assert "--force" in result.stdout


def test_workspace_export_all_happy_path(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    output = tmp_path / "export-all.zip"

    result = runner.invoke(
        app,
        ["workspace", "export", "--output", str(output)],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert output.is_file()
    assert "index_count" in result.stdout


def test_workspace_export_one_slug_happy_path(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    slug = _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    output = tmp_path / "export-one.zip"

    result = runner.invoke(
        app,
        ["workspace", "export", "--output", str(output), "--slug", slug],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert output.is_file()


def test_workspace_import_help() -> None:
    result = runner.invoke(app, ["workspace", "import", "--help"])
    assert result.exit_code == 0
    assert "--archive" in result.stdout
    assert "--force" in result.stdout


def test_workspace_import_happy_path(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    archive = tmp_path / "export.zip"
    export_result = runner.invoke(
        app,
        ["workspace", "export", "--output", str(archive)],
        env=_env(workspace_dir, source_dir),
    )
    assert export_result.exit_code == 0

    import_target = tmp_path / "import-workspace"
    clear_settings_cache()
    import_result = runner.invoke(
        app,
        ["workspace", "import", "--archive", str(archive)],
        env={
            "ARK_WORKSPACE_DIR": str(import_target),
            "ARK_SOURCE_DIR": str(source_dir),
        },
    )
    clear_settings_cache()
    assert import_result.exit_code == 0, import_result.stdout + import_result.stderr
    assert "imported_count" in import_result.stdout
    assert "local-sample" in import_result.stdout


def test_workspace_import_conflict_without_force_exits_nonzero(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    archive = tmp_path / "export.zip"
    runner.invoke(
        app,
        ["workspace", "export", "--output", str(archive)],
        env=_env(workspace_dir, source_dir),
    )

    result = runner.invoke(
        app,
        ["workspace", "import", "--archive", str(archive)],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert "already exists" in result.stderr or "already exists" in result.stdout


def test_workspace_import_conflict_with_force_succeeds(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    archive = tmp_path / "export.zip"
    runner.invoke(
        app,
        ["workspace", "export", "--output", str(archive)],
        env=_env(workspace_dir, source_dir),
    )

    result = runner.invoke(
        app,
        ["workspace", "import", "--archive", str(archive), "--force"],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code == 0
    assert "imported_count" in result.stdout


def test_workspace_export_existing_without_force_exits_nonzero(
    workspace_env: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    workspace_dir, source_dir = workspace_env
    _ingest_sample(workspace_dir, source_dir, index_name="local-sample")
    output = tmp_path / "export.zip"
    output.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["workspace", "export", "--output", str(output)],
        env=_env(workspace_dir, source_dir),
    )
    assert result.exit_code != 0
    assert "already exists" in result.stderr or "already exists" in result.stdout
