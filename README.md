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
- Minimal built-in web UI at `/` (named workspace indexes, paste text, browser .txt import, local file ingest, ask)
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

## Quickstart

One command initializes local storage, creates a sample text source, builds a workspace index, and verifies the RAG loop with the mock LLM — no Pi hardware, models, Chroma, or network required:

```bash
ark quickstart
ark quickstart --force   # rebuild if the sample index already exists
```

Start the web UI and use the **Quickstart** panel for the same flow in a browser:

```bash
ark serve --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/
```

Quickstart uses local sample text under `ARK_SOURCE_DIR` and the mock LLM backend only. Use **LLM diagnostics** (`ark llm test`) when you want to test a real OpenAI-compatible backend such as ark-llm.

## Deployment templates

Render reviewable example env and systemd files for the future two-Pi appliance. **This does not install services, configure networking, or mutate the host.**

```bash
ark deploy render --output-dir deploy/generated
ark deploy render --role rag --output-dir /tmp/ark-rag-deploy --force
ark deploy render --role llm --output-dir /tmp/ark-llm-deploy --force
```

Generated files include:

- **ark-rag** — `ark-rag.env` and `ark-rag.service` for running `ark serve` on the RAG Pi
- **ark-llm** — `ark-llm.env` and `ark-llm.service` for a future llama.cpp OpenAI-compatible server on the LLM Pi

Copy and adapt these files manually on each Pi. Installing units under `/etc/systemd/system`, enabling services, and configuring WiFi/Ethernet remain future work. See `deploy/rag-pi/` and `deploy/llm-pi/` for placeholders.

### Deployment preflight

After rendering templates, run dry-run deployment preflight to inspect whether expected files and planned install paths look sane. **This does not install services, render templates automatically, or mutate the host.**

```bash
ark deploy render --output-dir deploy/generated --force
ark deploy preflight --generated-dir deploy/generated
ark deploy preflight --generated-dir deploy/generated --role rag
ark deploy preflight --generated-dir deploy/generated --role llm --json
```

Warnings about missing `/opt/ark-pi/.venv/bin/ark`, llama.cpp binaries, or model files are expected on a dev laptop before Pi install. **Appliance preflight** (`ark preflight`) checks workspace/application readiness; **deployment preflight** checks rendered deployment templates and paths named in those files.

### Deployment install plan

After rendering templates and running deployment preflight, generate a dry-run install plan with planned copy targets and manual commands. **The plan does not copy files, run sudo, call systemctl, or mutate the host.**

```bash
ark deploy render --output-dir deploy/generated --force
ark deploy preflight --generated-dir deploy/generated
ark deploy plan --generated-dir deploy/generated
ark deploy plan --generated-dir deploy/generated --role rag
ark deploy plan --generated-dir deploy/generated --role llm --format markdown
ark deploy plan --generated-dir deploy/generated --format json --output /tmp/ark-plan.json
```

Commands shown in the plan are manual review steps for a future Pi install. Warnings about missing `/opt` paths are expected on a dev laptop.

### Deployment bundle

After rendering templates, running deployment preflight, and generating an install plan, package everything into a portable review archive. **The bundle does not install services, copy files into system directories, run sudo, call systemctl, or mutate the host.**

```bash
ark deploy render --output-dir deploy/generated --force
ark deploy preflight --generated-dir deploy/generated
ark deploy plan --generated-dir deploy/generated
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-deploy-bundle.zip --force
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-rag-bundle.zip --role rag --force
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-llm-bundle.zip --role llm --force
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-deploy-bundle.zip --json
```

The zip contains rendered templates for the selected role, deployment preflight JSON, install plan JSON and markdown, a checksum manifest, and a short README. Copy the archive to another machine for human review before any manual Pi install.

### Deployment bundle verification

After creating a bundle, verify it read-only before copying to another machine. **Verification opens the zip in memory, validates the manifest, checks SHA-256 checksums, and confirms dry-run safety flags. It does not extract files, write files, or install services.**

```bash
ark deploy render --output-dir deploy/generated --force
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-deploy-bundle.zip --force
ark deploy verify-bundle --bundle /tmp/ark-deploy-bundle.zip
ark deploy verify-bundle --bundle /tmp/ark-deploy-bundle.zip --json
```

Verification confirms role-specific template contents, rejects unsafe archive entries, and fails if the embedded install plan claims any step was performed.

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

With the server running (`ark serve --host 127.0.0.1 --port 8000`), open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in a browser.

**Paste and build:** use the **Add text** panel — set index name `sample`, paste document text, click **Build index**. Indexes live under `./data/workspace` by default (`ARK_WORKSPACE_DIR`).

**Import from browser:** use the **Import text file** panel — choose a local `.txt` file from your device. The browser reads the file and sends its text through the existing ingest API. No backend file upload.

**Ask:** pick an index from the dropdown and click **Ask**. No filesystem paths required for normal use.

**Delete:** use **Delete selected index** in the Ask panel to remove a stale index after confirmation.

Or ingest via curl (workspace mode):

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/text \
  -H 'Content-Type: application/json' \
  -d '{"title":"sample","text":"The RAG Pi owns prompt assembly.","index_name":"sample","use_workspace":true,"force":true}'
curl http://127.0.0.1:8000/api/indexes
```

Raw path ingest remains available for dev: `"use_workspace": false` with explicit `chunks_path` and `index_dir`.

## Local file ingest

Server-side text files under the configured source directory (`ARK_SOURCE_DIR`, default `./data/sources`) can be ingested into named workspace indexes. This is **not** browser file upload — files must already exist on the machine running ark-rag.

```bash
mkdir -p data/sources
printf 'Ark Pi can ingest local text files.\n' > data/sources/sample.txt
```

**Web UI:** use the **Add local file** panel — set index name and source path `sample.txt`, click **Build from local file**.

**API:**

```bash
curl -X POST http://127.0.0.1:8000/api/ingest/path \
  -H 'Content-Type: application/json' \
  -d '{"index_name":"local-sample","source_path":"sample.txt","force":true}'
```

**CLI:**

```bash
ark workspace ingest-path --source sample.txt --index-name local-sample --force
```

Supports a single `.txt` file or a directory of `.txt` files. Source paths are resolved safely inside `ARK_SOURCE_DIR` — path traversal and paths outside the source directory are rejected.

## Browser text file import

Pick a `.txt` file from your phone or laptop in the **Import text file** panel. The browser reads the file locally (via `FileReader` or `file.text()`) and sends the text to `POST /api/ingest/text`. This is **not** backend multipart upload — raw files are not stored on the server.

Only plain `.txt` / `text/plain` files are supported. PDF, DOCX, HTML, and Markdown parsing are future work.

## Workspace index management

Named workspace indexes can be deleted from the web UI (**Delete selected index**) or via `DELETE /api/indexes/{slug}`. Deletion removes the index directory under `ARK_WORKSPACE_DIR/indexes/<slug>/` and updates `catalog.json`. Deletes are constrained to the configured workspace — they never touch `source_dir` or paths outside the workspace.

### Workspace CLI

```bash
ark workspace list
ark workspace show --slug local-sample
ark workspace delete --slug local-sample --yes
```

`ark workspace delete` requires `--yes` to confirm. `ark workspace ingest-path` continues to build indexes from server-side files under `ARK_SOURCE_DIR`.

```bash
ark workspace export --output /tmp/ark-workspace-export.zip
ark workspace export --output /tmp/sample-only.zip --slug sample
```

Export writes a local zip on the machine running ark-rag (catalog, index data, and `export_manifest.json`). The built-in web UI can also **Download export** to save a zip directly in your browser via `POST /api/workspace/export/download` — no server-side output path required.

### Workspace import

Import restores an Ark Pi workspace export zip into the configured workspace. The built-in web UI supports **Upload and import** (raw `application/zip` body to `POST /api/workspace/import/upload`) or **Import from path** for zips already on the machine running ark-rag. No multipart upload is used.

```bash
ark workspace import --archive /tmp/ark-workspace-export.zip
ark workspace import --archive /tmp/sample-only.zip --force
```

Import validates archive structure, prevents path traversal, remaps catalog paths to the current `ARK_WORKSPACE_DIR`, and merges imported indexes with the existing catalog. Use `--force` to replace indexes that already exist. Browser upload size is limited by `ARK_MAX_IMPORT_BYTES` (default 50 MiB).

### LLM diagnostics

Check which LLM backend ark-rag is configured to use and run an explicit diagnostic test. Passive status does **not** contact the LLM server.

```bash
ark llm status
ark llm test --llm-backend mock
ark llm test --llm-backend openai-compatible --llm-base-url http://192.168.50.2:8080
```

The web UI **LLM diagnostics** panel calls `GET /api/llm/status` on load and `POST /api/llm/test` only when you click **Test LLM**. For production, point `ARK_LLM_BACKEND=openai-compatible` and `ARK_LLM_BASE_URL` at the ark-llm llama.cpp server.

### Local appliance init

Create configured workspace and source directories, optionally seed an empty catalog and a sample text file. Init only prepares local storage paths — it does not configure networking, systemd, or install models.

```bash
ark init
ark init --sample
ark init --json
```

Run `ark preflight` afterward to review passive readiness. The web UI **Initialize appliance storage** panel calls `POST /api/init`.

### Appliance preflight

Run a passive readiness checklist for paths, catalog health, index backends, source ingest, import limits, and LLM configuration. Preflight does **not** contact the LLM server — use `ark llm test` for an active check.

```bash
ark preflight
ark preflight --json
```

The web UI **Appliance preflight** panel calls `GET /api/preflight` on load and when you click **Run preflight**.

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
