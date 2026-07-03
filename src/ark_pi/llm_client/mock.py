from ark_pi.llm_client.types import LlmRequest, LlmResponse


class MockLlmClient:
    """Deterministic mock backend for local/dev testing. No network calls."""

    def complete(self, request: LlmRequest) -> LlmResponse:
        prompt_length = len(request.prompt)
        text = (
            "Mock LLM backend: no real model was called.\n"
            "\n"
            f"Received a prompt with {prompt_length} characters.\n"
            "This confirms retrieval, prompt assembly, and LLM client wiring are connected."
        )
        return LlmResponse(
            text=text,
            backend="mock",
            model=request.model,
        )
