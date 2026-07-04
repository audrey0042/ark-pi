# Ark Pi Architecture

## Two-Pi layout

```
                    +------------------+
                    |  Phone / Laptop  |
                    +--------+---------+
                             | WiFi
                             v
+------------------+  Ethernet   +------------------+
|     ark-rag      |<----------->|     ark-llm      |
|  (Raspberry Pi)  |             |  (Raspberry Pi)  |
+------------------+             +------------------+
```

## What runs on ark-rag

- WiFi access point for client devices
- Web UI / dashboard
- RAG API (FastAPI)
- Document ingestion pipeline
- Text extraction, chunking, embedding, vector indexing
- Index backend abstraction: simple lexical fallback for offline dev; optional Chroma vector storage on ark-rag
- Chroma vector database storage (optional backend; not required for laptop dev/tests)
- Context retrieval and prompt assembly
- LLM client boundary (`ark_pi.llm_client`) — mock backend for local dev, OpenAI-compatible HTTP client for future ark-llm calls over Ethernet

## What runs on ark-llm

- llama.cpp server only
- GGUF model file storage
- Receives fully assembled prompts from ark-rag
- Returns generated text responses

ark-llm does not know about documents, Chroma, WiFi, or the web UI.

## Why ark-rag owns retrieval and prompt assembly

Retrieval requires access to the vector index, embedding model, and source document metadata — all of which live on the RAG Pi. Prompt assembly combines retrieved chunks with the user's question and system instructions. Keeping this logic on ark-rag means:

- The LLM Pi stays simple and stateless
- Index rebuilds happen in one place
- The inference Pi can be swapped or upgraded independently

## Why ark-llm stays stateless

The LLM Pi is a dedicated inference worker. It receives a complete prompt and returns text. No document state, no session history, no index — just model weights and llama.cpp. This separation keeps memory free for the model and avoids coupling inference to retrieval logic.

## Request flow

```
Phone/Laptop
  -> WiFi AP on ark-rag
  -> Web UI (GET /) on ark-rag
  -> POST /api/ingest/text (paste text or browser-imported text -> chunks + index) or POST /api/ingest/path (local file) or POST /api/ask
  -> Index search on ark-rag (simple lexical or optional Chroma)
  -> Prompt assembly on ark-rag
  -> LLM client on ark-rag (mock locally; openai-compatible over Ethernet in production)
  -> llama.cpp server on ark-llm
  -> Response back to ark-rag
  -> Answer shown in browser
```

## FastAPI layer (laptop dev)

The RAG API and built-in web UI live in `ark_pi.web`:

```
Browser
  -> GET / or /ui  -> built-in HTML (inline CSS/JS, no CDN)
  -> GET /api/indexes -> workspace catalog (local catalog.json)
  -> DELETE /api/indexes/{slug} -> catalog-aware index deletion
  -> POST /api/workspace/export -> local zip backup of catalog + indexes
  -> POST /api/workspace/export/download -> browser-downloadable zip (no output path)
  -> POST /api/workspace/import -> restore from local export zip (server-side path)
  -> POST /api/workspace/import/upload -> browser upload of raw application/zip body
  -> POST /api/ingest/text -> workspace ingest -> chunking + rag_index.build_index + catalog upsert
  -> POST /api/ingest/path -> source_dir .txt file/dir -> same pipeline + catalog upsert
  -> POST /api/ask -> rag_ask.run_ask -> search + prompting + llm_client
  -> POST /api/search -> rag_index.search_index
  -> GET /api/llm/status -> passive LLM config (no network)
  -> POST /api/llm/test -> explicit LLM diagnostic prompt
  -> POST /api/init -> create local workspace/source directories (explicit mutation)
  -> POST /api/quickstart -> init + sample ingest + mock ask smoke (explicit mutation)
  -> GET /api/deploy/preflight -> dry-run deployment template readiness (no host mutations)
  -> GET /api/deploy/plan -> dry-run deployment install plan (no host mutations)
  -> GET /api/preflight -> passive appliance readiness checklist (no network)
  -> GET /api/status -> sanitized config, passive LLM summary, and preflight summary (no network probes)
```

Source documents for local file ingest live under `source_dir` (`ARK_SOURCE_DIR`, default `./data/sources`). The API and web UI resolve paths safely inside that directory — arbitrary server paths are not accepted. **Browser text file import** reads `.txt` files in the browser and sends their contents to `POST /api/ingest/text`; raw files are not uploaded or stored server-side in this slice. Backend multipart upload, PDF/DOCX parsing, and OCR are future work.

Named indexes live under `workspace_dir` (`ARK_WORKSPACE_DIR`, default `./data/workspace`). The catalog is local JSON metadata in `catalog.json` — not a remote database and not discovered by scanning arbitrary paths. The web UI is a thin client over these endpoints with a catalog-aware lifecycle: create (ingest), list, select, delete, export, and import. Delete and export operations derive paths from `workspace_dir/indexes/<slug>/` rather than trusting stored catalog paths. **Workspace export** writes a local zip archive (`catalog.json`, `export_manifest.json`, and index files) via CLI, server-side path API, or browser download (`POST /api/workspace/export/download` streams an in-memory zip). **Workspace import** restores from an Ark Pi export zip: server-side path import via CLI/`POST /api/workspace/import`, or browser upload via `POST /api/workspace/import/upload` with a raw `application/zip` request body (no multipart, no `python-multipart`). Uploaded archives are validated before any workspace writes; catalog paths are remapped to the current workspace. **Web text ingest** accepts pasted plain text or browser-read `.txt` file contents; **local file ingest** reads server-side `.txt` files already on disk. The API does not import `chromadb` at startup; Chroma loads only when a request selects that backend.

## Local development

During scaffold and early development, work happens on a laptop with `ARK_ROLE=dev`. No Pi hardware or external services are required.

The default LLM backend is `mock` (`ARK_LLM_BACKEND=mock`). It validates retrieval, prompt assembly, and client wiring without network calls, llama.cpp, or model files. The `openai-compatible` backend is intended for future llama.cpp server use on ark-llm and is opt-in only. **LLM diagnostics** expose passive status (`GET /api/llm/status`, `ark llm status`) without contacting ark-llm, and an explicit active test (`POST /api/llm/test`, `ark llm test`) that sends a tiny diagnostic prompt through the configured client when you choose to verify connectivity. **Local appliance init** (`POST /api/init`, `ark init`) explicitly creates workspace and source directories, optionally seeds an empty catalog and sample text source, then runs passive preflight. **Quickstart** (`POST /api/quickstart`, `ark quickstart`) composes init, sample source ingest, index build, and a mock-LLM ask smoke test into one offline dev/appliance flow. **Appliance preflight** (`GET /api/preflight`, `ark preflight`) runs a passive operator checklist for workspace paths, catalog health, source ingest readiness, index backends, import limits, and LLM configuration without hidden network probes or directory creation.

The default index backend is `simple` (`ARK_INDEX_BACKEND=simple`). It provides deterministic lexical search for offline laptop development and tests. The optional `chroma` backend lazy-loads `chromadb` only when selected and is intended for future ark-rag vector storage — install with `pip install -e '.[chroma]'` when ready. Semantic embedding model selection is a future slice. See the root README for details.

## Two-Pi deployment (future)

Production targets two Raspberry Pi nodes: **ark-rag** runs the web UI, FastAPI API, workspace catalog, ingest, indexing, prompt assembly, and LLM client; **ark-llm** runs an OpenAI-compatible llama.cpp server. **Deployment template rendering** (`ark deploy render`) writes reviewable example env and systemd files for both roles without installing units, calling `systemctl`, or configuring host networking. **Deployment preflight** (`ark deploy preflight`, `GET /api/deploy/preflight`) inspects those rendered templates and the paths they reference in a dry-run pass before any future install step — it does not render, copy, or enable services. **Deployment install plan** (`ark deploy plan`, `GET /api/deploy/plan`) composes preflight with a structured list of planned file copies and manual commands for operator review; it does not execute those steps. **Deployment bundle** (`ark deploy bundle`) packages rendered templates, preflight output, install plan reports, and a SHA-256 manifest into a portable zip for operator review on another machine; it does not install services or mutate host state. Actual systemd installation, WiFi AP setup, Ethernet addressing, llama.cpp build, and model placement remain future slices.
