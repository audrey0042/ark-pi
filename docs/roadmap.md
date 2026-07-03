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

## 5. LLM client boundary / mock backend

Typed LLM client interface in `ark_pi.llm_client` with a deterministic mock backend (default) and an OpenAI-compatible HTTP client for future llama.cpp use. `ark ask` calls the configured backend after retrieval and prompt assembly. Network calls are opt-in only.

**Status: done**

## 6. Optional Chroma backend boundary

Index backend selection (`simple` default, `chroma` optional) with lazy-loaded Chroma storage behind the existing index abstraction. Manifest records backend identity. No semantic embedding pipeline yet.

**Status: done**

## 7. Explicit embedding model pipeline

Choose and wire an embedding model for semantic indexing. Evaluate retrieval quality offline.

## 8. Real semantic retrieval and evaluation

End-to-end semantic search, ranking evaluation, and tuning over Chroma-backed indexes.

## 9. FastAPI RAG service

Local FastAPI endpoints for health, config-safe status, index stats, search, and ask over the existing index and LLM client boundaries. Mock LLM default; Chroma opt-in. Laptop-safe and fully testable with FastAPI TestClient.

**Status: done**

## 10. llama.cpp server deployment

Deploy llama.cpp on ark-llm Pi. ark-rag uses the existing OpenAI-compatible client over Ethernet. Real inference and model files — not required for laptop dev/tests.

## 11. Minimal web UI

Built-in single-page HTML served at `GET /` and `GET /ui`. Calls local `POST /api/ask` from inline JavaScript — no npm, CDN, or build chain. Phone-friendly layout for future ark-rag use.

**Status: done**

## 12. Web text ingest

Browser and API path to paste plain text, write chunks JSONL, and build a local index via `POST /api/ingest/text`. Reuses existing chunking and index facades. No file uploads or document parsers.

**Status: done**

## 13. Workspace index catalog

Named indexes under `workspace_dir` with local `catalog.json` metadata. `GET /api/indexes`, workspace-mode text ingest, and web UI index dropdown — no raw filesystem paths for normal use.

**Status: done**

## 14. WiFi AP and systemd deployment

Production deployment on both Pis: static Ethernet, WiFi AP on ark-rag, systemd units, storage mounts. See `deploy/`.

## 15. SimpleWiki ingest

Ingest a SimpleWiki dump (or subset) as a reference corpus. Dump files stay out of git.

## 16. Backup / export / import strategy

Export and restore indexes and config. Support rebuilding from source vs. restoring snapshots.

---

## Future idea: dev lab (not planned yet)

Two simulated nodes — containerized ark-rag and ark-llm — for laptop integration testing. The ark-llm container could initially serve a mock OpenAI-compatible endpoint. Real llama.cpp inference remains out of scope until stage 8.
