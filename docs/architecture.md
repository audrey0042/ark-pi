# Ark Pi Architecture

Start on a laptop: [README quickstart](../README.md#quickstart).

## Two-Pi layout

Target: local docs + local inference, no cloud required.

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
- LLM client boundary (`ark_pi.llm_client`): mock for local dev, OpenAI-compatible HTTP for ark-llm over Ethernet

## What runs on ark-llm

- llama.cpp server only
- GGUF model file storage
- Receives fully assembled prompts from ark-rag
- Returns generated text responses

ark-llm does not know about documents, Chroma, WiFi, or the web UI.

## Why ark-rag owns retrieval and prompt assembly

Retrieval needs the index, embeddings, and source metadata, all on the RAG Pi. Prompt assembly combines chunks with the user's question. Keeping this on ark-rag means:

- The LLM Pi stays simple and stateless
- Index rebuilds happen in one place
- The inference Pi can be swapped or upgraded independently

## Why ark-llm stays stateless

The LLM Pi runs inference only. Prompt in, text out. No docs, sessions, or index on that box. Keeps RAM for the model.

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

Source documents for local file ingest live under `source_dir` (`ARK_SOURCE_DIR`, default `./data/sources`). The API and web UI only accept paths inside that directory. **Browser text file import** reads `.txt` files in the browser and sends their contents to `POST /api/ingest/text`; raw files are not uploaded or stored server-side in this slice. Backend multipart upload, PDF/DOCX parsing, and OCR are future work.

Named indexes live under `workspace_dir` (`ARK_WORKSPACE_DIR`, default `./data/workspace`). The catalog is local JSON in `catalog.json`, not a remote DB or a directory scan. The web UI is a thin client over these endpoints with a catalog-aware lifecycle: create (ingest), list, select, delete, export, and import. Delete and export operations derive paths from `workspace_dir/indexes/<slug>/` rather than trusting stored catalog paths. **Workspace export** writes a local zip archive (`catalog.json`, `export_manifest.json`, and index files) via CLI, server-side path API, or browser download (`POST /api/workspace/export/download` streams an in-memory zip). **Workspace import** restores from an Ark Pi export zip: server-side path import via CLI/`POST /api/workspace/import`, or browser upload via `POST /api/workspace/import/upload` with a raw `application/zip` request body (no multipart, no `python-multipart`). Uploaded archives are validated before any workspace writes; catalog paths are remapped to the current workspace. **Web text ingest** accepts pasted plain text or browser-read `.txt` file contents; **local file ingest** reads server-side `.txt` files already on disk. The API does not import `chromadb` at startup; Chroma loads only when a request selects that backend.

## Local development

During scaffold and early development, work happens on a laptop with `ARK_ROLE=dev`. No Pi hardware or external services are required.

The default LLM backend is `mock` (`ARK_LLM_BACKEND=mock`). It validates retrieval, prompt assembly, and client wiring without network calls, llama.cpp, or model files. The `openai-compatible` backend is for ark-llm via llama.cpp. Opt-in only. **LLM diagnostics** expose passive status (`GET /api/llm/status`, `ark llm status`) without contacting ark-llm, and an explicit active test (`POST /api/llm/test`, `ark llm test`) that sends a tiny diagnostic prompt through the configured client when you choose to verify connectivity. **Local appliance init** (`POST /api/init`, `ark init`) explicitly creates workspace and source directories, optionally seeds an empty catalog and sample text source, then runs passive preflight. **Quickstart** (`POST /api/quickstart`, `ark quickstart`) composes init, sample source ingest, index build, and a mock-LLM ask smoke test into one offline dev/appliance flow. **Appliance preflight** (`GET /api/preflight`, `ark preflight`) runs a passive operator checklist for workspace paths, catalog health, source ingest readiness, index backends, import limits, and LLM configuration without hidden network probes or directory creation.

The default index backend is `simple` (`ARK_INDEX_BACKEND=simple`). It provides deterministic lexical search for offline laptop development and tests. The optional `chroma` backend lazy-loads `chromadb` when selected. Install with `pip install -e '.[chroma]'` if you want it. Semantic embedding model selection is a future slice. See the root README for details.

## Two-Pi deployment (future)

**ark-rag**: web UI, API, workspace, ingest, indexing, prompts, LLM client. **ark-llm**: llama.cpp server.

`ark deploy *` commands only build/review artifacts. They don't install units or configure the network. See [README](../README.md#deployment-artifacts) and [two-pi-manual.md](deployment/two-pi-manual.md).

Future one-line bootstrap: [install.sh](../install.sh) installs apt-based OS prerequisites on Debian-family hosts (first observed on Raspberry Pi 5 / Debian 13 trixie), prepares default `/opt/ark-pi` and `/srv/ark-pi` ownership with sudo when needed, bootstraps the app unprivileged, renders templates, runs env-aware validation (loads role env before `ark preflight` / `ark llm status`), and can install service files with `--install-services`. llama.cpp/models/network still manual. Spec: [installer-bootstrap-contract.md](deployment/installer-bootstrap-contract.md).

Systemd, WiFi AP, Ethernet, llama.cpp build, and model placement are still manual/TODO.
