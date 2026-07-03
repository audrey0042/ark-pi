# Roadmap

Staged development plan for Ark Pi.

## 1. Scaffold and config

Project structure, pydantic-settings config layer, minimal Typer CLI (`ark version`, `ark status`, `ark config`), docs, deployment placeholders, offline smoke tests.

**Status: done**

## 2. Local document chunking

`ark ingest chunk` reads `.txt`, directories of `.txt`, or `.jsonl` sources and writes deterministic chunk records to JSONL. Offline tests cover splitting, source loading, and CLI behavior.

**Status: done**

## 3. Local index abstraction / simple retrieval

`ark index build|search|stats` with a pure-Python lexical `simple` backend. Index interface boundary in `ark_pi.rag` so Chroma can plug in later.

**Status: done**

## 4. RAG prompt assembly / dev ask

`ark ask` searches the local index, assembles a deterministic RAG prompt, and returns an honest dev/mock answer. No LLM calls yet.

**Status: done**

## 5. Chroma indexing

Embed chunks and write to Chroma. Rebuild index from source on demand.

## 6. Retrieval API

FastAPI endpoints for semantic search over the local index. Return ranked chunks with scores.

## 7. llama.cpp server integration

HTTP client from ark-rag to ark-llm. Send assembled prompts, receive completions. ark-llm runs llama.cpp only.

## 8. Minimal web UI

Simple dashboard on ark-rag: ask a question, show retrieved context and answer.

## 9. WiFi AP and systemd deployment

Production deployment on both Pis: static Ethernet, WiFi AP on ark-rag, systemd units, storage mounts. See `deploy/`.

## 10. SimpleWiki ingest

Ingest a SimpleWiki dump (or subset) as a reference corpus. Dump files stay out of git.

## 11. Backup / export / import strategy

Export and restore indexes and config. Support rebuilding from source vs. restoring snapshots.

---

## Future idea: dev lab (not planned yet)

Two simulated nodes — containerized ark-rag and ark-llm — for laptop integration testing. The ark-llm container could initially serve a mock OpenAI-compatible endpoint. Real llama.cpp inference remains out of scope until stage 7.
