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

## 14. Local file ingest

Server-side `.txt` file and directory ingest from `source_dir` (`ARK_SOURCE_DIR`) into named workspace indexes. `POST /api/ingest/path`, web UI **Add local file** panel, and `ark workspace ingest-path`. Safe path containment; no browser upload or document parsers.

**Status: done**

## 15. Browser text file import

Browser-side `.txt` import in the built-in web UI. JavaScript reads the selected file locally and sends its text to the existing `POST /api/ingest/text` endpoint. No backend multipart upload, no raw file storage, no parser dependencies.

**Status: done**

## 16. Workspace index management

Catalog-aware deletion of named workspace indexes. `DELETE /api/indexes/{slug}` and web UI **Delete selected index** with confirmation. Deletes are constrained to `ARK_WORKSPACE_DIR`; catalog entries are removed after filesystem cleanup.

**Status: done**

## 17. Workspace CLI management

Terminal parity for workspace indexes: `ark workspace list`, `show`, and `delete` (with `--yes`). Reuses catalog-aware helpers; no filesystem scanning beyond the workspace catalog.

**Status: done**

## 18. Workspace export

Local backup of workspace catalog and named indexes to a zip archive. `ark workspace export`, `POST /api/workspace/export`, and web UI **Export workspace** panel. Stdlib `zipfile` only; paths derived from workspace layout.

**Status: done**

## 19. Browser workspace export download

Download workspace export zips directly in the browser. `POST /api/workspace/export/download` returns an in-memory zip; web UI **Download export** button. Reuses existing export validation and archive-building logic. Server-side path export unchanged.

**Status: done**

## 20. Browser workspace import upload

Upload and restore workspace export zips directly from the browser. `POST /api/workspace/import/upload` accepts raw `application/zip` (no multipart); web UI **Upload and import** button. Reuses safe importer validation; size limited by `ARK_MAX_IMPORT_BYTES` (default 50 MiB). Server-side path import unchanged.

**Status: done**

## 21. LLM backend diagnostics

Passive LLM status and explicit diagnostic test across CLI (`ark llm status`, `ark llm test`), API (`GET /api/llm/status`, `POST /api/llm/test`), and web UI **LLM diagnostics** panel. Passive endpoints do not contact ark-llm; active test uses the existing LLM client boundary.

**Status: done**

## 22. Local appliance init

Explicit initialization across CLI (`ark init`), API (`POST /api/init`), and web UI **Initialize appliance storage** panel. Creates `ARK_WORKSPACE_DIR`, `ARK_SOURCE_DIR`, workspace indexes directory, optionally empty `catalog.json` and sample text source, then reports passive preflight. Does not configure networking, systemd, or models.

**Status: done**

## 23. Quickstart sample index

One-step dev/appliance smoke flow across CLI (`ark quickstart`), API (`POST /api/quickstart`), and web UI **Quickstart** panel. Initializes local storage, creates sample text source, builds a named workspace index, and verifies the RAG loop with the mock LLM. No network, Chroma, or real model required.

**Status: done**

## 24. Deployment template rendering

Dry-run rendering of ark-rag and ark-llm env/systemd templates via CLI (`ark deploy render`). Generates reviewable examples under a chosen output directory without installing units, calling systemctl, or configuring networking.

**Status: done**

## 25. Appliance preflight readiness

Passive operator checklist across CLI (`ark preflight`), API (`GET /api/preflight`), and web UI **Appliance preflight** panel. Checks workspace/source paths, catalog health, index roots, source ingest readiness, index backend availability, passive LLM config, import limits, and disk space without network calls or directory creation.

**Status: done**

## 26. WiFi AP and systemd deployment

Production deployment on both Pis: static Ethernet, WiFi AP on ark-rag, systemd units, storage mounts. See `deploy/`.

## 27. SimpleWiki ingest

Ingest a SimpleWiki dump (or subset) as a reference corpus. Dump files stay out of git.

## 28. Workspace import / restore

Restore workspace indexes from Ark Pi export archives. `ark workspace import`, `POST /api/workspace/import`, server-side path UI, and browser upload via `POST /api/workspace/import/upload`. Validates archive structure, remaps catalog paths, merges with existing catalog.

**Status: done**

## 29. Backup / export / import strategy

Export and restore indexes and config. Support rebuilding from source vs. restoring snapshots.

---

## Future idea: dev lab (not planned yet)

Two simulated nodes — containerized ark-rag and ark-llm — for laptop integration testing. The ark-llm container could initially serve a mock OpenAI-compatible endpoint. Real llama.cpp inference remains out of scope until stage 8.
