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
- GGUF model file at `/srv/ark-pi/models/model.gguf` (appliance data under `$DATA_DIR/models`; optional installer download via `--download-model`)
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
  -> ark appliance ask-smoke -> isolated smoke source + ark-smoke index + rag_ask.run_ask + cleanup (CLI)
  -> ark appliance receipt -> offline validation receipt; optional Slice 48/49 smoke embed (CLI)
  -> GET /api/deploy/preflight -> dry-run deployment template readiness (no host mutations)
  -> GET /api/deploy/plan -> dry-run deployment install plan (no host mutations)
  -> GET /api/preflight -> passive appliance readiness checklist (no network)
  -> GET /api/status -> sanitized config, passive LLM summary, and preflight summary (no network probes)
```

Source documents for local file ingest live under `source_dir` (`ARK_SOURCE_DIR`, default `./data/sources`). The API and web UI only accept paths inside that directory. **Browser text file import** reads `.txt` files in the browser and sends their contents to `POST /api/ingest/text`; raw files are not uploaded or stored server-side in this slice. Backend multipart upload, PDF/DOCX parsing, and OCR are future work.

Named indexes live under `workspace_dir` (`ARK_WORKSPACE_DIR`, default `./data/workspace`). The catalog is local JSON in `catalog.json`, not a remote DB or a directory scan. The web UI is a thin client over these endpoints with a catalog-aware lifecycle: create (ingest), list, select, delete, export, and import. Delete and export operations derive paths from `workspace_dir/indexes/<slug>/` rather than trusting stored catalog paths. **Workspace export** writes a local zip archive (`catalog.json`, `export_manifest.json`, and index files) via CLI, server-side path API, or browser download (`POST /api/workspace/export/download` streams an in-memory zip). **Workspace import** restores from an Ark Pi export zip: server-side path import via CLI/`POST /api/workspace/import`, or browser upload via `POST /api/workspace/import/upload` with a raw `application/zip` request body (no multipart, no `python-multipart`). Uploaded archives are validated before any workspace writes; catalog paths are remapped to the current workspace. **Web text ingest** accepts pasted plain text or browser-read `.txt` file contents; **local file ingest** reads server-side `.txt` files already on disk. The API does not import `chromadb` at startup; Chroma loads only when a request selects that backend.

## Bulk corpus ingest (CLI service boundary)

Large offline corpora use the **corpus ingest service** in `ark_pi.corpus`, not synchronous FastAPI ingest endpoints. The CLI (`ark corpus ingest`, `ark corpus status`, `ark corpus prepare-wikipedia`) is a thin adapter over reusable service functions.

```
Wikimedia XML dump (operator download)
  -> ark corpus prepare-wikipedia (source-specific normalization)
  -> canonical JSONL + manifest + attribution

Source (JSONL or .txt tree)
  -> stream documents in batches
  -> deterministic chunking (ark_pi.ingest.chunking)
  -> incremental simple index append (ark_pi.rag.simple_index)
  -> workspace catalog upsert
  -> checkpoint + completion ledger under workspace/corpus-runs/<run-id>/
```

Run state never lives in the git checkout. **Corpus preparation** (dump normalization to JSONL), **indexing**, and **inference** remain separate concerns. Article provenance is preserved in prepared JSONL metadata; chunk records currently index title, source, and text.

**Embedding boundary:** canonical chunk JSONL is backend-neutral. Slice 53 adds an optional local embedding runtime (`ark_pi.embeddings`) for passive status, active tests, and offline evaluation. Slice 54 wires the same runtime into resumable corpus ingest for Chroma-backed semantic indexes (`ark_pi.rag.semantic_index`). Semantic **query** execution (`/api/search`, `ark ask`) is not wired yet (Slice 8). Operators must supply offline model artifacts under `/srv/ark-pi/embedding-models` before real (non-mock) semantic indexing. See [embeddings.md](embeddings.md), [corpus-ingest.md](corpus-ingest.md), and [wikipedia-corpus.md](wikipedia-corpus.md).

## Local development

During scaffold and early development, work happens on a laptop with `ARK_ROLE=dev`. No Pi hardware or external services are required.

The default LLM backend is `mock` (`ARK_LLM_BACKEND=mock`). It validates retrieval, prompt assembly, and client wiring without network calls, llama.cpp, or model files. The `openai-compatible` backend is for ark-llm via llama.cpp. Opt-in only. **LLM diagnostics** expose passive status (`GET /api/llm/status`, `ark llm status`) without contacting ark-llm, and an explicit active test (`POST /api/llm/test`, `ark llm test`) that sends a tiny diagnostic prompt through the configured client when you choose to verify connectivity. **Local appliance init** (`POST /api/init`, `ark init`) explicitly creates workspace and source directories, optionally seeds an empty catalog and sample text source, then runs passive preflight. **Quickstart** (`POST /api/quickstart`, `ark quickstart`) composes init, sample source ingest, index build, and a mock-LLM ask smoke test into one offline dev/appliance flow. **Appliance ask smoke** (`ark appliance ask-smoke`) runs an isolated end-to-end RAG validation on real appliances: writes `ark-pi-smoke-beacon.txt` under `source_dir`, builds/refreshes the dedicated `ark-smoke` workspace index, verifies retrieval of the beacon phrase (`copper lantern`), calls `rag_ask.run_ask` through the configured LLM backend, validates the generated answer, and cleans up smoke artifacts by default. **Appliance validation receipts** (`ark appliance receipt`) collect versioned JSON evidence for RAG or LLM installs: host/software metadata, allowlisted configuration, filesystem and deployment preflight checks, read-only systemd state, and optional embedded Slice 48/49 smoke results when `--run-smoke` or `--run-ask-smoke` is explicitly requested. Receipt collection is observational and offline by default; it does not start services or perform hidden network probes. **Appliance preflight** (`GET /api/preflight`, `ark preflight`) runs a passive operator checklist for workspace paths, catalog health, source ingest readiness, index backends, import limits, and LLM configuration without hidden network probes or directory creation.

The default index backend is `simple` (`ARK_INDEX_BACKEND=simple`). It provides deterministic lexical search for offline laptop development and tests. The optional `chroma` backend lazy-loads `chromadb` when selected. Install with `pip install -e '.[chroma]'` if you want semantic indexing. **Embedding diagnostics** (`ark embeddings status|test|evaluate`) prove local model compatibility. **Semantic corpus indexing** (`ark corpus ingest --backend chroma`) embeds chunks incrementally with resume; lexical ingest and search remain the default. Semantic search is a follow-up slice. See [embeddings.md](embeddings.md) and the root README.

## Two-Pi deployment

**ark-rag**: web UI, API, workspace, ingest, indexing, prompts, OpenAI-compatible LLM client (talks to ark-llm over HTTP). **ark-llm**: `llama-server` from llama.cpp, OpenAI-compatible HTTP API on port 8080.

ark-rag depends on `ARK_LLM_BASE_URL` in `/etc/ark-pi/ark-rag.env` to reach ark-llm. The installer renders this at install time via `--llm-base-url` or `--partner-ip` (role `rag` or `both`). Default when unset: `http://ark-llm.local:8080`. Network auto-discovery is future work; operators supply a reachable IP or hostname today.

`ark deploy *` commands build/review artifacts only. [install.sh](../install.sh) bootstraps the app, renders templates, validates, optionally installs systemd units, and can build llama.cpp with `--llama-build`. GGUF model placement and network/WiFi remain manual. See [two-pi-manual.md](deployment/two-pi-manual.md) and [installer-bootstrap-contract.md](deployment/installer-bootstrap-contract.md).

WiFi AP and Ethernet routing are still manual/TODO.
