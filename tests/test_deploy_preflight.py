from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ark_pi.deploy.preflight import run_deployment_preflight
from ark_pi.deploy.templates import render_deployment_templates
from ark_pi.web.app import create_app


@pytest.fixture
def rendered_dir(tmp_path: Path) -> Path:
    render_deployment_templates(tmp_path, force=True)
    return tmp_path


def test_preflight_all_passes_or_warns_after_render_all(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="all")

    assert result.overall_status in {"ready", "warning"}
    assert result.host_mutations_performed is False
    assert result.network_checks_performed is False
    check_ids = {check.id for check in result.checks}
    assert "generated_dir" in check_ids
    assert "template_files" in check_ids
    assert "rag_ark_binary" in check_ids
    assert "llm_model_path" in check_ids


def test_preflight_rag_requires_rag_env_and_service(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="rag")

    assert result.role == "rag"
    template_check = next(c for c in result.checks if c.id == "template_files")
    assert template_check.status == "pass"
    assert set(template_check.details["expected"]) == {"ark-rag.env", "ark-rag.service"}


def test_preflight_llm_requires_llm_env_and_service(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="llm")

    template_check = next(c for c in result.checks if c.id == "template_files")
    assert template_check.status == "pass"
    assert set(template_check.details["expected"]) == {"ark-llm.env", "ark-llm.service"}


def test_preflight_missing_generated_dir_produces_blocked(tmp_path: Path) -> None:
    missing = tmp_path / "missing-generated"

    result = run_deployment_preflight(missing)

    assert result.overall_status == "blocked"
    generated_check = next(c for c in result.checks if c.id == "generated_dir")
    assert generated_check.status == "fail"


def test_preflight_missing_expected_template_file_produces_blocked(
    rendered_dir: Path,
) -> None:
    (rendered_dir / "ark-rag.env").unlink()

    result = run_deployment_preflight(rendered_dir, role="rag")

    assert result.overall_status == "blocked"
    template_check = next(c for c in result.checks if c.id == "template_files")
    assert template_check.status == "fail"


def test_preflight_wrong_role_content_produces_blocked(rendered_dir: Path) -> None:
    rag_env = rendered_dir / "ark-rag.env"
    rag_env.write_text("ARK_ROLE=llm\n", encoding="utf-8")

    result = run_deployment_preflight(rendered_dir, role="rag")

    assert result.overall_status == "blocked"
    content_check = next(c for c in result.checks if c.id == "template_content")
    assert content_check.status == "fail"


def test_preflight_malformed_env_line_produces_blocked(rendered_dir: Path) -> None:
    rag_env = rendered_dir / "ark-rag.env"
    rag_env.write_text("ARK_ROLE=rag\nnot-valid\n", encoding="utf-8")

    result = run_deployment_preflight(rendered_dir, role="rag")

    assert result.overall_status == "blocked"
    env_check = next(c for c in result.checks if c.id == "env_parse")
    assert env_check.status == "fail"


def test_preflight_rag_localhost_llm_base_url_produces_warning(rendered_dir: Path) -> None:
    rag_env = rendered_dir / "ark-rag.env"
    content = rag_env.read_text(encoding="utf-8")
    rag_env.write_text(
        content.replace(
            "ARK_LLM_BASE_URL=http://ark-llm.local:8080",
            "ARK_LLM_BASE_URL=http://127.0.0.1:8080",
        ),
        encoding="utf-8",
    )

    result = run_deployment_preflight(rendered_dir, role="rag")

    url_check = next(c for c in result.checks if c.id == "rag_llm_base_url")
    assert url_check.status == "warning"


def test_preflight_rag_malformed_llm_base_url_produces_blocked(rendered_dir: Path) -> None:
    rag_env = rendered_dir / "ark-rag.env"
    content = rag_env.read_text(encoding="utf-8")
    rag_env.write_text(
        content.replace(
            "ARK_LLM_BASE_URL=http://ark-llm.local:8080",
            "ARK_LLM_BASE_URL=10.255.255.101:8080",
        ),
        encoding="utf-8",
    )

    result = run_deployment_preflight(rendered_dir, role="rag")

    assert result.overall_status == "blocked"
    url_check = next(c for c in result.checks if c.id == "rag_llm_base_url")
    assert url_check.status == "fail"
    assert "http://" in url_check.message


def test_preflight_rag_lan_ip_llm_base_url_produces_pass(rendered_dir: Path) -> None:
    rag_env = rendered_dir / "ark-rag.env"
    content = rag_env.read_text(encoding="utf-8")
    rag_env.write_text(
        content.replace(
            "ARK_LLM_BASE_URL=http://ark-llm.local:8080",
            "ARK_LLM_BASE_URL=http://10.255.255.101:8080",
        ),
        encoding="utf-8",
    )

    result = run_deployment_preflight(rendered_dir, role="rag")

    url_check = next(c for c in result.checks if c.id == "rag_llm_base_url")
    assert url_check.status == "pass"


def test_preflight_rag_missing_ark_binary_produces_warning(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="rag")

    binary_check = next(c for c in result.checks if c.id == "rag_ark_binary")
    assert binary_check.status == "warning"


def test_preflight_llm_missing_llama_binary_produces_warning(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="llm")

    binary_check = next(c for c in result.checks if c.id == "llm_llama_binary")
    assert binary_check.status == "warning"


def test_preflight_llm_missing_model_path_produces_warning(rendered_dir: Path) -> None:
    result = run_deployment_preflight(rendered_dir, role="llm")

    model_check = next(c for c in result.checks if c.id == "llm_model_path")
    assert model_check.status == "warning"


def test_preflight_invalid_llm_port_produces_blocked(rendered_dir: Path) -> None:
    llm_env = rendered_dir / "ark-llm.env"
    content = llm_env.read_text(encoding="utf-8")
    llm_env.write_text(
        content.replace("ARK_LLAMA_PORT=8080", "ARK_LLAMA_PORT=not-a-port"),
        encoding="utf-8",
    )

    result = run_deployment_preflight(rendered_dir, role="llm")

    assert result.overall_status == "blocked"
    port_check = next(c for c in result.checks if c.id == "llm_port")
    assert port_check.status == "fail"


def test_preflight_performs_no_network_checks(rendered_dir: Path) -> None:
    with patch("ark_pi.llm_client.openai_compat.httpx.post") as post:
        result = run_deployment_preflight(rendered_dir)

    post.assert_not_called()
    assert result.network_checks_performed is False


def test_preflight_performs_no_host_mutations(rendered_dir: Path) -> None:
    with patch.object(Path, "write_text") as write_text:
        result = run_deployment_preflight(rendered_dir)

    write_text.assert_not_called()
    assert result.host_mutations_performed is False


def test_api_deploy_preflight_returns_response_shape(rendered_dir: Path) -> None:
    client = TestClient(create_app())
    response = client.get(
        "/api/deploy/preflight",
        params={"generated_dir": str(rendered_dir), "role": "all"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] in {"ready", "warning", "blocked"}
    assert data["host_mutations_performed"] is False
    assert data["network_checks_performed"] is False
    assert isinstance(data["checks"], list)
