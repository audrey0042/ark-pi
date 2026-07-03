from collections.abc import Sequence

from ark_pi.rag.index import SearchResult


def make_dev_answer(question: str, results: Sequence[SearchResult], _prompt: str) -> str:
    chunk_count = len(results)
    chunk_label = "chunk" if chunk_count == 1 else "chunks"
    return (
        "Dev answer mode: no LLM configured.\n"
        "\n"
        f"Retrieved {chunk_count} context {chunk_label} for:\n"
        f'"{question}"\n'
        "\n"
        "The assembled prompt is ready for a future LLM backend."
    )
