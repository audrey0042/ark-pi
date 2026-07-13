from pathlib import Path

import pytest

from ark_pi.deploy.templates import (
    ARK_LLM_ENV,
    ARK_LLM_SERVICE,
    ARK_RAG_ENV,
    ARK_RAG_SERVICE,
    LlmRenderConfig,
    RagRenderConfig,
    render_deployment_templates,
    validate_output_dir,
)


def test_render_all_returns_four_files(tmp_path: Path) -> None:
    result = render_deployment_templates(tmp_path)

    assert len(result.generated_files) == 4
    assert result.role == "all"
    filenames = {Path(generated.path).name for generated in result.generated_files}
    assert filenames == {"ark-rag.env", "ark-rag.service", "ark-llm.env", "ark-llm.service"}


def test_render_rag_returns_only_rag_files(tmp_path: Path) -> None:
    result = render_deployment_templates(tmp_path, role="rag")

    assert len(result.generated_files) == 2
    assert result.role == "rag"
    filenames = {Path(generated.path).name for generated in result.generated_files}
    assert filenames == {"ark-rag.env", "ark-rag.service"}


def test_render_llm_returns_only_llm_files(tmp_path: Path) -> None:
    result = render_deployment_templates(tmp_path, role="llm")

    assert len(result.generated_files) == 2
    assert result.role == "llm"
    filenames = {Path(generated.path).name for generated in result.generated_files}
    assert filenames == {"ark-llm.env", "ark-llm.service"}


def test_rendered_ark_rag_env_contains_role_rag(tmp_path: Path) -> None:
    render_deployment_templates(tmp_path, role="rag")

    content = (tmp_path / "ark-rag.env").read_text(encoding="utf-8")
    assert "ARK_ROLE=rag" in content
    assert content == ARK_RAG_ENV


def test_rendered_ark_rag_service_runs_ark_serve(tmp_path: Path) -> None:
    render_deployment_templates(tmp_path, role="rag")

    content = (tmp_path / "ark-rag.service").read_text(encoding="utf-8")
    assert "ark serve" in content
    assert content == ARK_RAG_SERVICE


def test_rendered_ark_llm_env_contains_role_llm(tmp_path: Path) -> None:
    render_deployment_templates(tmp_path, role="llm")

    content = (tmp_path / "ark-llm.env").read_text(encoding="utf-8")
    assert "ARK_ROLE=llm" in content
    assert content == ARK_LLM_ENV


def test_rendered_ark_llm_service_references_llama_server_variables(tmp_path: Path) -> None:
    render_deployment_templates(tmp_path, role="llm")

    content = (tmp_path / "ark-llm.service").read_text(encoding="utf-8")
    assert "${ARK_LLAMA_BIN}" in content
    assert "${ARK_MODEL_PATH}" in content
    assert "WorkingDirectory=" in content
    assert content == ARK_LLM_SERVICE


def test_render_llm_with_custom_paths(tmp_path: Path) -> None:
    config = LlmRenderConfig(
        prefix="/custom/prefix",
        llama_bin="/custom/prefix/vendor/llama.cpp/build/bin/llama-server",
        model_dir="/custom/data/models",
        model_path="/custom/data/models/custom.gguf",
    )
    render_deployment_templates(tmp_path, role="llm", force=True, llm_config=config)

    env_content = (tmp_path / "ark-llm.env").read_text(encoding="utf-8")
    assert "ARK_LLAMA_BIN=/custom/prefix/vendor/llama.cpp/build/bin/llama-server" in env_content
    assert "ARK_MODEL_PATH=/custom/data/models/custom.gguf" in env_content
    service_content = (tmp_path / "ark-llm.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/custom/prefix" in service_content


def test_existing_file_without_force_fails(tmp_path: Path) -> None:
    (tmp_path / "ark-rag.env").write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to overwrite"):
        render_deployment_templates(tmp_path, role="rag")


def test_existing_file_with_force_overwrites_generated_file(tmp_path: Path) -> None:
    stale = tmp_path / "ark-rag.env"
    stale.write_text("existing", encoding="utf-8")

    render_deployment_templates(tmp_path, role="rag", force=True)

    assert stale.read_text(encoding="utf-8") == ARK_RAG_ENV


def test_refuses_output_dir_under_etc() -> None:
    with pytest.raises(ValueError, match="Refusing to write deployment templates under /etc"):
        validate_output_dir(Path("/etc/ark-pi-deploy"))


def test_refuses_output_dir_exactly_etc() -> None:
    with pytest.raises(ValueError, match="Refusing to write deployment templates under /etc"):
        validate_output_dir(Path("/etc"))


def test_render_creates_output_dir(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "generated"
    result = render_deployment_templates(output, role="rag")

    assert output.is_dir()
    assert result.output_dir == str(output.resolve())


def test_render_rag_with_custom_llm_base_url(tmp_path: Path) -> None:
    config = RagRenderConfig(llm_base_url="http://10.255.255.101:8080")
    render_deployment_templates(tmp_path, role="rag", force=True, rag_config=config)

    content = (tmp_path / "ark-rag.env").read_text(encoding="utf-8")
    assert "ARK_LLM_BASE_URL=http://10.255.255.101:8080" in content
    assert content != ARK_RAG_ENV


def test_render_all_with_rag_llm_base_url_override(tmp_path: Path) -> None:
    config = RagRenderConfig(llm_base_url="http://10.255.255.101:8080")
    render_deployment_templates(tmp_path, role="all", force=True, rag_config=config)

    rag_content = (tmp_path / "ark-rag.env").read_text(encoding="utf-8")
    llm_content = (tmp_path / "ark-llm.env").read_text(encoding="utf-8")
    assert "ARK_LLM_BASE_URL=http://10.255.255.101:8080" in rag_content
    assert llm_content == ARK_LLM_ENV
