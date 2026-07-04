from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ark_pi.deploy.plan import (
    build_deployment_install_plan,
    plan_to_dict,
    render_plan_markdown,
    validate_plan_output_path,
    write_plan_output,
)
from ark_pi.deploy.templates import render_deployment_templates
from ark_pi.web.app import create_app


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


def test_build_plan_all_includes_rag_and_llm_copy_steps(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir, role="all")

    copy_ids = {step.id for step in plan.copy_steps}
    assert copy_ids == {"copy_rag_env", "copy_rag_service", "copy_llm_env", "copy_llm_service"}
    command_roles = {command.role for command in plan.manual_commands}
    assert command_roles == {"rag", "llm"}


def test_build_plan_rag_includes_only_rag_steps(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir, role="rag")

    assert plan.role == "rag"
    assert {step.role for step in plan.copy_steps} == {"rag"}
    assert {command.role for command in plan.manual_commands} == {"rag"}


def test_build_plan_llm_includes_only_llm_steps(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir, role="llm")

    assert plan.role == "llm"
    assert {step.role for step in plan.copy_steps} == {"llm"}
    assert {command.role for command in plan.manual_commands} == {"llm"}


def test_every_copy_step_has_performed_false(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)

    assert plan.copy_steps
    assert all(step.performed is False for step in plan.copy_steps)


def test_every_manual_command_has_performed_false(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)

    assert plan.manual_commands
    assert all(command.performed is False for command in plan.manual_commands)


def test_plan_reports_no_host_or_network_mutations(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)

    assert plan.dry_run is True
    assert plan.host_mutations_performed is False
    assert plan.network_checks_performed is False


def test_blocked_preflight_prevents_plan_generation(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"

    with pytest.raises(ValueError, match="deployment preflight is blocked"):
        build_deployment_install_plan(missing)


def test_markdown_render_includes_dry_run_safety_statement(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)
    markdown = render_plan_markdown(plan)

    assert "# Ark Pi Deployment Install Plan" in markdown
    assert "This plan did not install services." in markdown
    assert "This plan did not run sudo." in markdown
    assert "This plan did not call systemctl." in markdown
    assert "This plan did not write to system directories." in markdown


def test_json_shape_includes_copy_steps_and_manual_commands(rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)
    payload = plan_to_dict(plan)

    assert isinstance(payload["copy_steps"], list)
    assert isinstance(payload["manual_commands"], list)
    assert payload["copy_steps"][0]["performed"] is False
    assert payload["manual_commands"][0]["performed"] is False
    assert "preflight" in payload


def test_output_path_under_etc_is_rejected() -> None:
    with pytest.raises(ValueError, match="Refusing to write plan output under /etc"):
        validate_plan_output_path(Path("/etc/ark-pi-plan.md"))


def test_existing_output_without_force_fails(tmp_path: Path, rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)
    output = tmp_path / "plan.md"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to overwrite"):
        write_plan_output(output, render_plan_markdown(plan))


def test_existing_output_with_force_succeeds(tmp_path: Path, rendered_dir: Path) -> None:
    plan = build_deployment_install_plan(rendered_dir)
    output = tmp_path / "plan.md"
    output.write_text("existing", encoding="utf-8")

    write_plan_output(output, render_plan_markdown(plan), force=True)

    assert "Deployment Install Plan" in output.read_text(encoding="utf-8")


def test_api_deploy_plan_returns_json_shape(rendered_dir: Path) -> None:
    client = TestClient(create_app())
    response = client.get(
        "/api/deploy/plan",
        params={"generated_dir": str(rendered_dir), "role": "all"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["host_mutations_performed"] is False
    assert len(data["copy_steps"]) == 4


def test_api_deploy_plan_blocked_returns_400(tmp_path: Path) -> None:
    client = TestClient(create_app())
    missing = tmp_path / "missing-generated"
    response = client.get(
        "/api/deploy/plan",
        params={"generated_dir": str(missing), "role": "all"},
    )

    assert response.status_code == 400
