from collections.abc import Sequence

from ark_pi.rag.index import SearchResult


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def build_rag_prompt(question: str, results: Sequence[SearchResult]) -> str:
    normalized_question = _normalize_whitespace(question)
    lines = [
        "You are Ark Pi, a local offline RAG assistant.",
        "",
        "Answer the question using only the provided context.",
        "If the context does not contain the answer, say that the local index does not contain enough information.",
        "",
        "Context:",
    ]

    if not results:
        lines.append("No context chunks retrieved.")
    else:
        for index, result in enumerate(results, start=1):
            lines.extend(
                [
                    f"[{index}] Title: {result.title}",
                    f"Source: {result.source}",
                    f"Chunk ID: {result.id}",
                    "Text:",
                    _normalize_whitespace(result.text),
                    "",
                ]
            )

    lines.extend(
        [
            "Question:",
            normalized_question,
            "",
            "Answer:",
        ]
    )
    return "\n".join(lines)
