from ark_pi.rag.index import SearchResult
from ark_pi.rag.prompting import build_rag_prompt


def _result(
    *,
    id: str = "doc:000000:abc123",
    title: str = "RAG Pi",
    source: str = "doc.txt",
    chunk_index: int = 0,
    text: str = "The RAG Pi owns retrieval and prompt assembly.",
) -> SearchResult:
    return SearchResult(
        score=2.0,
        id=id,
        title=title,
        source=source,
        chunk_index=chunk_index,
        text=text,
    )


def test_build_rag_prompt_with_one_result() -> None:
    question = "Which Pi owns prompt assembly?"
    result = _result()
    prompt = build_rag_prompt(question, [result])

    assert "Title: RAG Pi" in prompt
    assert "Source: doc.txt" in prompt
    assert "Chunk ID: doc:000000:abc123" in prompt
    assert "The RAG Pi owns retrieval and prompt assembly." in prompt
    assert "Question:" in prompt
    assert question in prompt
    assert "Answer:" in prompt


def test_build_rag_prompt_with_multiple_results_preserves_order() -> None:
    first = _result(id="first:000000:aaa", title="First", text="First chunk text.")
    second = _result(id="second:000000:bbb", title="Second", text="Second chunk text.")
    prompt = build_rag_prompt("Order test?", [first, second])

    assert prompt.index("[1] Title: First") < prompt.index("[2] Title: Second")
    assert "First chunk text." in prompt
    assert "Second chunk text." in prompt


def test_build_rag_prompt_is_deterministic() -> None:
    results = [_result()]
    question = "Deterministic prompt?"
    first = build_rag_prompt(question, results)
    second = build_rag_prompt(question, results)
    assert first == second


def test_build_rag_prompt_collapses_whitespace() -> None:
    result = _result(text="The   RAG Pi\n\nowns   prompt assembly.")
    prompt = build_rag_prompt("Whitespace?", [result])
    assert "The RAG Pi owns prompt assembly." in prompt


def test_build_rag_prompt_with_empty_results() -> None:
    prompt = build_rag_prompt("No context?", [])
    assert "Context:" in prompt
    assert "No context chunks retrieved." in prompt
    assert "Question:" in prompt
    assert "No context?" in prompt
