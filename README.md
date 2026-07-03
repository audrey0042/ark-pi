# Ark Pi

Ark Pi is a two-Raspberry-Pi offline RAG appliance. You connect a phone or laptop to WiFi on the **RAG Pi**, ask questions through a web UI, and get answers grounded in locally indexed documents — with inference running on a separate **LLM Pi** over Ethernet. No cloud required.

## Architecture

Two Raspberry Pi 5 devices connected directly over Ethernet:

| Device | Role |
|--------|------|
| **ark-rag** | WiFi access point, web UI, RAG API, document ingestion, embedding/indexing (Chroma), retrieval, prompt assembly |
| **ark-llm** | llama.cpp server only — receives assembled prompts, returns generated text |

The repo contains the **recipe**, not generated artifacts. Each Pi can rebuild its local index from source documents. Models, indexes, and logs are disposable runtime data.

See [docs/architecture.md](docs/architecture.md) for the full design.

## Project status

**Initial scaffold plus local chunking, lexical index/search, RAG prompt assembly, and a mock LLM client boundary.** This repo is not a finished appliance. It provides project structure, configuration, a CLI with offline chunking, simple retrieval, prompt assembly, and mock LLM responses, plus documentation and smoke tests. Chroma semantic indexing, retrieval API, web UI, llama.cpp deployment, and Pi deployment are not implemented yet.

## Local laptop development

Current development happens on a normal Ubuntu laptop — not on either Pi.

- Default role: `ARK_ROLE=dev`
- Safe local paths: `./data`, `./indexes`, `./models`
- No Pi hardware, WiFi AP, Ethernet link, llama.cpp, Chroma, or model files required
- All tests pass offline

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

ark version
ark status
ark config
python -m pytest
```

Copy `.env.example` to `.env` if you want to override defaults.

## Local chunking

Read local source documents and write deterministic chunk records to JSONL:

```bash
ark ingest chunk --input samples/docs --output /tmp/ark_chunks.jsonl
ark ingest chunk --input /path/to/doc.txt --output /tmp/doc_chunks.jsonl
ark ingest chunk --input data/source.jsonl --output data/chunks/source_chunks.jsonl
```

Supported inputs: a single `.txt` file, a directory of `.txt` files, or a `.jsonl` file with `title` and `text` fields per record.

Options: `--chunk-size` (default 1000), `--chunk-overlap` (default 200), `--force` to overwrite an existing output file.

Generated `.jsonl` chunk files are runtime artifacts and must not be committed (already excluded via `.gitignore`).

## Local indexing and search

Build a simple lexical index from chunk JSONL and search it offline:

```bash
ark ingest chunk --input samples/docs --output /tmp/ark_chunks.jsonl --force
ark index build --chunks /tmp/ark_chunks.jsonl --index-dir /tmp/ark_index --force
ark index stats --index-dir /tmp/ark_index
ark index search --index-dir /tmp/ark_index --query "offline rag" --limit 3
```

The current `simple` backend uses deterministic token overlap scoring — not semantic vector search. It validates the retrieval flow on a laptop without Chroma, embeddings, or model files. Semantic search with Chroma comes later.

Generated indexes under `indexes/` or `/tmp/` are runtime artifacts and must not be committed.

## LLM client boundary / Mock LLM backend

`ark ask` searches the local index, assembles a RAG prompt, and calls the configured LLM client. By default it uses the **mock** backend — fully offline, no llama.cpp server or model files required:

```bash
ark ask --index-dir /tmp/ark_index --question "Which Pi owns generation?" --show-context
ark ask --index-dir /tmp/ark_index --question "Which Pi owns prompt assembly?" --show-prompt
```

The mock backend returns a deterministic response that confirms retrieval, prompt assembly, and client wiring are connected. It does not pretend to be real intelligence.

Test the client boundary directly:

```bash
ark llm mock --prompt "hello"
```

Future opt-in HTTP example (not required for local tests — needs a running llama.cpp OpenAI-compatible server on ark-llm):

```bash
ark ask \
  --index-dir /tmp/ark_index \
  --question "Which Pi owns generation?" \
  --llm-backend openai-compatible \
  --llm-base-url http://192.168.50.2:8080
```

Configure defaults via `.env` (`ARK_LLM_BACKEND=mock` for local dev). See `.env.example`.

## What belongs in git

- Source code under `src/`
- Documentation under `docs/`
- Deployment placeholders under `deploy/` (READMEs only for now)
- Tests, `pyproject.toml`, `.env.example`

## What must not be committed

- Virtual environments (`.venv/`)
- Environment secrets (`.env`)
- Generated data (`data/`, `indexes/`, `logs/`, `chroma_store/`)
- Model files (`models/`, `*.gguf`, `*.bin`, `*.safetensors`)
- Dump and index artifacts (`*.jsonl`, `*.jsonl.zst`, `*.tar.zst`, `*.xml.bz2`, `*.sqlite3`, `*.duckdb`)

## Future setup: ark-rag

Placeholder — not ready for production use.

1. Install Python 3.12 and clone this repo on the RAG Pi.
2. Copy `.env.example` to `.env` and uncomment the **RAG Pi** section.
3. Mount NVMe storage at `/srv/ark-pi/` (strongly preferred over MicroSD for index writes).
4. See [deploy/rag-pi/README.md](deploy/rag-pi/README.md) for future networking, WiFi AP, and systemd notes.

## Future setup: ark-llm

Placeholder — not ready for production use.

1. Install Python 3.12 and clone this repo on the LLM Pi.
2. Copy `.env.example` to `.env` and uncomment the **LLM Pi** section.
3. Place GGUF model files under `/srv/ark-pi/models/` (not in git).
4. See [deploy/llm-pi/README.md](deploy/llm-pi/README.md) for future llama.cpp build and systemd notes.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).
