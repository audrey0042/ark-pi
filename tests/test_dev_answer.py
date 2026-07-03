from ark_pi.rag.dev_answer import make_dev_answer
from ark_pi.rag.index import SearchResult
from ark_pi.rag.prompting import build_rag_prompt


def _result(
    *,
    id: str = "doc:000000:abc123",
    text: str = "The RAG Pi owns retrieval.",
) -> SearchResult:
    return SearchResult(
        score=1.0,
        id=id,
        title="RAG Pi",
        source="doc.txt",
        chunk_index=0,
        text=text,
    )


def test_make_dev_answer_states_no_llm_configured() -> None:
    question = "Which Pi owns retrieval?"
    results = [_result()]
    prompt = build_rag_prompt(question, results)
    answer = make_dev_answer(question, results, prompt)

    assert "Dev answer mode" in answer
    assert "no LLM configured" in answer


def test_make_dev_answer_includes_chunk_count() -> None:
    question = "Chunk count?"
    results = [_result(), _result(id="doc:000001:def456", text="Second chunk.")]
    prompt = build_rag_prompt(question, results)
    answer = make_dev_answer(question, results, prompt)

    assert "Retrieved 2 context chunks" in answer


def test_make_dev_answer_includes_question() -> None:
    question = "Which Pi owns prompt assembly?"
    results = [_result()]
    prompt = build_rag_prompt(question, results)
    answer = make_dev_answer(question, results, prompt)

    assert '"Which Pi owns prompt assembly?"' in answer


def test_make_dev_answer_does_not_claim_factual_answer() -> None:
    chunk_text = "The RAG Pi owns retrieval and prompt assembly."
    question = "Which Pi owns prompt assembly?"
    results = [_result(text=chunk_text)]
    prompt = build_rag_prompt(question, results)
    answer = make_dev_answer(question, results, prompt)

    assert chunk_text not in answer
    assert "ready for a future LLM backend" in answer
