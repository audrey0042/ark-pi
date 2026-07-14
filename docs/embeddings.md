# Local embedding runtime

Slice 53 adds a typed optional embedding runtime for diagnostics, offline evaluation, and **semantic corpus indexing** (Slice 54). Lexical `simple` retrieval remains the default for `/api/search` and `ark ask`.

## Backends

| Backend | Purpose |
|---------|---------|
| `mock` (default) | Deterministic offline vectors for tests and CLI contract checks. Not semantically meaningful. |
| `sentence-transformers` | Optional real local model for Pi compatibility probes. Requires `pip install -e '.[embeddings]'`. |

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `ARK_EMBEDDING_BACKEND` | `mock` | `mock` or `sentence-transformers` |
| `ARK_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model identifier when remote resolution is allowed, or descriptive name for a local directory |
| `ARK_EMBEDDING_MODEL_PATH` | *(unset)* | Preferred local model directory. When set, loads without network |
| `ARK_EMBEDDING_DIMENSIONS` | `384` | Expected output dimensions; validated when nonzero |
| `ARK_EMBEDDING_BATCH_SIZE` | `16` | Texts per inference batch |
| `ARK_EMBEDDING_NORMALIZE` | `true` | Request L2-normalized vectors when supported |
| `ARK_EMBEDDING_DEVICE` | `cpu` | Only `cpu` is supported in this slice |
| `ARK_EMBEDDING_ALLOW_NETWORK` | `false` | Must be explicit to permit remote model resolution |

Default application paths remain network-free. No model is downloaded implicitly.

## Optional dependency installation

```bash
pip install -e '.[embeddings]'
```

The `sentence-transformers` package is pure Python (`py3-none-any`). **PyTorch** is the main compatibility risk on Python 3.14 / aarch64 (Raspberry Pi 5). If wheels are unavailable, keep `ARK_EMBEDDING_BACKEND=mock` and record the failure for a follow-up slice.

`install.sh --with-embeddings` is deferred until real-Pi dependency probing confirms a viable wheel path. Manual installation is documented here instead.

## Local model layout (appliance)

Prepare a model on an internet-connected machine, then copy the directory to the RAG Pi:

```bash
# On a connected machine (example)
python -m pip install sentence-transformers
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2').save('/tmp/all-MiniLM-L6-v2')"

# On ark-rag
sudo mkdir -p /srv/ark-pi/embedding-models
sudo chown audrey:audrey /srv/ark-pi/embedding-models
rsync -a /tmp/all-MiniLM-L6-v2/ ark-rag:/srv/ark-pi/embedding-models/all-MiniLM-L6-v2/
```

Set in `/etc/ark-pi/ark-rag.env`:

```bash
ARK_EMBEDDING_BACKEND=sentence-transformers
ARK_EMBEDDING_MODEL_PATH=/srv/ark-pi/embedding-models/all-MiniLM-L6-v2
ARK_EMBEDDING_ALLOW_NETWORK=false
```

Do not store embedding models under `/opt/ark-pi` or in git.

## CLI diagnostics

### Passive status (no model load, no network)

```bash
ark embeddings status
ark embeddings status --env-file /etc/ark-pi/ark-rag.env
ark embeddings status --json
```

### Active test (loads embedder, runs inference)

```bash
ark embeddings test --env-file /etc/ark-pi/ark-rag.env
ark embeddings test --model-path /srv/ark-pi/embedding-models/all-MiniLM-L6-v2
ark embeddings test --text 'how to purify drinking water' --json
```

Reports dimensions, load/embedding latency, vector validity, and a cosine-similarity heuristic comparing related water texts vs an unrelated bicycle text. This is a diagnostic check, not a quality certification.

### Offline evaluation (no index writes)

```bash
ark embeddings evaluate --env-file /etc/ark-pi/ark-rag.env --json
ark embeddings evaluate --fixture ./my-fixture.json --json
```

Built-in fixture topics: water purification, wound cleaning, electrical safety, bicycle repair (neutral snippets only).

Metrics: `top1_accuracy`, `recall_at_3`, `mean_reciprocal_rank`, plus counts and `total_latency_ms`.

## API (optional)

- `GET /api/embeddings/status` — passive only
- `POST /api/embeddings/test` — active only

## Python 3.14 / aarch64 hardware probe

Run on the RAG Pi after merge:

```bash
python3 --version
uname -m
/opt/ark-pi/.venv/bin/python -m pip debug --verbose
cd /opt/ark-pi && /opt/ark-pi/.venv/bin/python -m pip install -e '.[embeddings]'
sudo /opt/ark-pi/.venv/bin/ark embeddings status --env-file /etc/ark-pi/ark-rag.env --json
sudo /opt/ark-pi/.venv/bin/ark embeddings test --env-file /etc/ark-pi/ark-rag.env --json
sudo /opt/ark-pi/.venv/bin/ark embeddings evaluate --env-file /etc/ark-pi/ark-rag.env --json
```

### Expected failure modes

| Symptom | Likely cause |
|---------|----------------|
| `EmbeddingDependencyMissing` | Optional extra not installed or PyTorch wheel missing |
| `EmbeddingNetworkDisabled` | No local model path and `ARK_EMBEDDING_ALLOW_NETWORK=false` |
| `EmbeddingModelMissing` | `ARK_EMBEDDING_MODEL_PATH` does not exist or is not a directory |
| `EmbeddingModelLoadFailed` | Corrupt or incomplete model directory |

## Corpus ingest integration (Slice 54)

Semantic corpus ingest (`ark corpus ingest --backend chroma`) uses this runtime to embed canonical chunks and write vectors to Chroma. Each index stores an **embedding fingerprint** (backend, model identity, dimensions, normalization). Resume and append reject incompatible embedding configuration.

```bash
# Passive config check (no model load)
ark embeddings status --json

# Smoke semantic ingest with mock embedder (no torch)
ark corpus ingest ./articles.jsonl --index wiki-semantic --backend chroma --json

# Offline sentence-transformers (model copied locally first)
export ARK_EMBEDDING_MODEL_PATH=/srv/ark-pi/embedding-models/all-MiniLM-L6-v2
ark corpus ingest ./articles.jsonl --index wiki-semantic --backend chroma \
  --embedding-backend sentence-transformers
```

Rebuild the index when changing model identity, dimensions, or normalization. See [corpus-ingest.md](corpus-ingest.md).

## What this slice does not do

- Does not make Chroma the default index backend
- Does not migrate or rebuild existing workspace indexes automatically
- Does not add semantic search to `/api/search` or change `ark ask` (deferred to Slice 8)
- Does not download models automatically
