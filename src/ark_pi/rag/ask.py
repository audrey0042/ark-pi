from dataclasses import dataclass
from pathlib import Path

from ark_pi import config as ark_config
from ark_pi.config import ArkSettings
from ark_pi.llm_client import LlmRequest, create_llm_client
from ark_pi.rag import index as rag_index
from ark_pi.rag import prompting
from ark_pi.rag.index import SearchResult

NO_CONTEXT_ANSWER = "No relevant context found."


@dataclass(frozen=True)
class AskResult:
    question: str
    answer: str
    retrieved_count: int
    results: list[SearchResult]
    prompt: str | None
    no_context: bool


def run_ask(
    index_dir: Path,
    question: str,
    *,
    limit: int = 5,
    backend: str | None = None,
    llm_backend: str | None = None,
    llm_base_url: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    settings: ArkSettings | None = None,
    timeout_seconds: float | None = None,
) -> AskResult:
    """Search the index, assemble a prompt, and call the configured LLM backend."""
    stripped_question = question.strip()
    if not stripped_question:
        msg = "Question must not be empty."
        raise ValueError(msg)

    resolved_settings = settings if settings is not None else ark_config.get_settings()
    resolved_max_tokens = (
        max_tokens if max_tokens is not None else resolved_settings.llm_max_tokens
    )
    resolved_temperature = (
        temperature if temperature is not None else resolved_settings.llm_temperature
    )
    if resolved_temperature < 0:
        msg = "temperature must be >= 0."
        raise ValueError(msg)

    resolved_llm_backend = (
        llm_backend if llm_backend is not None else resolved_settings.llm_backend
    )

    results = rag_index.search_index(
        index_dir,
        stripped_question,
        backend=backend,
        limit=limit,
    )

    if not results:
        return AskResult(
            question=stripped_question,
            answer=NO_CONTEXT_ANSWER,
            retrieved_count=0,
            results=[],
            prompt=None,
            no_context=True,
        )

    prompt = prompting.build_rag_prompt(stripped_question, results)
    base_url = (
        llm_base_url if llm_base_url is not None else resolved_settings.llm_base_url
    )
    resolved_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else resolved_settings.llm_timeout_seconds
    )
    client = create_llm_client(
        resolved_llm_backend,
        base_url=base_url if resolved_llm_backend == "openai-compatible" else None,
        timeout_seconds=resolved_timeout,
    )
    response = client.complete(
        LlmRequest(
            prompt=prompt,
            model=resolved_settings.llm_model,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
        )
    )

    return AskResult(
        question=stripped_question,
        answer=response.text,
        retrieved_count=len(results),
        results=results,
        prompt=prompt,
        no_context=False,
    )
