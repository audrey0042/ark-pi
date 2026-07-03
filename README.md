# Ark Pi

Ark Pi is an experimental two-Raspberry-Pi local RAG appliance.

The goal is simple: connect a phone or laptop to a small local WiFi box, ask questions, and get answers grounded in documents stored on the device. No cloud account, no hosted vector database, no remote inference service.

The target deployment uses two Raspberry Pi 5 devices. The **RAG Pi** (`ark-rag`) owns ingestion, indexing, retrieval, prompt assembly, and the web/API surface. The **LLM Pi** (`ark-llm`) runs llama.cpp inference and stores model files. They talk over Ethernet while clients connect to the RAG Pi over WiFi.

This repo holds the recipe and tooling — not generated indexes, model weights, or runtime data.

## Current status

Ark Pi is early-stage. It is **not** a finished appliance you can flash onto two Pis and forget about.

**Works today on a laptop, fully offline:**

- Document chunking (`ark ingest chunk`)
- Simple lexical index build and search (`ark index`)
- RAG prompt assembly and `ark ask`
- Local FastAPI RAG API (`ark serve`)
- Minimal built-in web UI at `/`
- Mock LLM backend for end-to-end wiring checks
- Project config, CLI, tests, and docs

**Still future work:**

- Semantic embeddings and real vector retrieval
- Chroma storage on ark-rag in production
- WiFi access point setup
- systemd deployment on both Pis
- llama.cpp server deployment on ark-llm

See [docs/roadmap.md](docs/roadmap.md) for the staged plan.

## Architecture

```text
Phone / laptop
      |
      | WiFi
      v
ark-rag
  - WiFi access point
  - web UI
  - RAG API (FastAPI)
  - document ingestion
  - chunking and indexing
  - retrieval and prompt assembly
      |
      | Ethernet
      v
ark-llm
  - llama.cpp server
  - local GGUF model files
  - text generation only
```

The RAG Pi keeps all document and index state. The LLM Pi stays stateless: it receives an assembled prompt and returns text.

For request flow, backend boundaries, and design rationale, see [docs/architecture.md](docs/architecture.md). Hardware and storage notes are in [docs/hardware.md](docs/hardware.md).

## Local development

Day-to-day work runs on a normal laptop with `ARK_ROLE=dev`. You do not need Pi hardware, WiFi, Ethernet, llama.cpp, Chroma, or model files for the default path.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

ark version
ark status
python -m pytest
```

Copy `.env.example` to `.env` only if you want to override defaults. Generated output goes under `./data`, `./indexes`, and `./models` locally — all excluded from git.

## Try the local RAG loop

This smoke test creates a sample document under `/tmp`, chunks it, builds the simple index, searches, and runs `ark ask`:

```bash
mkdir -p /tmp/ark_smoke_docs
cat > /tmp/ark_smoke_docs/ark-pi.txt << 'EOF'
Ark Pi splits work across two Raspberry Pis.

The RAG Pi owns document ingestion, chunking, indexing, retrieval, and prompt assembly.

The LLM Pi runs llama.cpp and generates text from assembled prompts.
EOF

ark ingest chunk --input /tmp/ark_smoke_docs --output /tmp/ark_chunks.jsonl --force
ark index build --chunks /tmp/ark_chunks.jsonl --index-dir /tmp/ark_index --force
ark index search --index-dir /tmp/ark_index --query "Which Pi owns generation?" --limit 3
ark ask --index-dir /tmp/ark_index --question "Which Pi owns prompt assembly?"
```

The mock backend confirms retrieval, prompt assembly, and LLM client wiring — it does not call a real model. Add `--show-context` or `--show-prompt` to inspect what `ark ask` assembled.

## API smoke test

Start the local API (mock LLM by default, no Chroma required):

```bash
ark serve --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"index_dir":"/tmp/ark_index","question":"Which Pi owns prompt assembly?"}'
```

Use the index path from the RAG loop smoke test above, or build your own with `ark index build`.

## Web UI smoke test

With the server running (`ark serve --host 127.0.0.1 --port 8000`), open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in a browser. Enter `/tmp/ark_index` (from the RAG loop above) and ask a question. The page calls `POST /api/ask` on the same host — no external assets or build step required.

## What is intentionally local-only right now

**Index backend:** The default `simple` backend uses deterministic token overlap scoring. It is good enough to exercise the retrieval pipeline on a laptop without embeddings or Chroma.

**LLM backend:** The default `mock` backend returns a deterministic response after search and prompt assembly. An OpenAI-compatible HTTP client exists for future llama.cpp use on ark-llm, but real inference is not part of the default dev path.

Deeper CLI options, backend flags, and optional Chroma experiments are documented in [docs/architecture.md](docs/architecture.md) and `.env.example`.

## Repository hygiene

**Belongs in git:** source under `src/`, docs under `docs/`, deployment placeholders under `deploy/`, tests, `pyproject.toml`, and `.env.example`.

**Must not be committed:**

- Virtual environments (`.venv/`)
- Secrets (`.env`)
- Generated data (`data/`, `indexes/`, `logs/`, `chroma_store/`)
- Model files (`models/`, `*.gguf`, `*.bin`, `*.safetensors`)
- Dump and index artifacts (`*.jsonl`, `*.jsonl.zst`, `*.tar.zst`, `*.xml.bz2`, `*.sqlite3`, `*.duckdb`)

The repo is meant to be rebuildable from source. Indexes, chunks, logs, models, and dumps are disposable runtime artifacts.

## Roadmap

Next major areas: embedding model pipeline, semantic retrieval, llama.cpp on ark-llm, and production deployment on both Pis.

Full staged plan: [docs/roadmap.md](docs/roadmap.md)

## License

See [LICENSE](LICENSE).
