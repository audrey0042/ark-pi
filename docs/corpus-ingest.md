# Corpus ingest

Bulk, resumable corpus ingestion for large offline datasets. Use this workflow to load JSONL corpora or directories of UTF-8 `.txt` files into a named workspace index on ark-rag. The LLM Pi is not required.

## CLI commands

```bash
# Start ingest
ark corpus ingest ./articles.jsonl --index simplewiki

# Directory of .txt files (recursive, stable lexical order)
ark corpus ingest /srv/ark-pi/data/sources/simplewiki --index simplewiki --batch-size 100

# Resume after interrupt or power loss (graceful stop only)
ark corpus ingest ./articles.jsonl --index simplewiki --resume

# Machine-readable output
ark corpus ingest ./articles.jsonl --index simplewiki --json

# Read-only status
ark corpus status
ark corpus status --run-id RUN_ID --json
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success or already completed |
| 1 | Fatal error |
| 2 | Partial completion, interrupted run, or failures with `--continue-on-error` |

## Input formats

### JSONL

One JSON object per line. Blank lines are ignored.

Canonical record shape:

```json
{"id":"article-1","title":"Water purification","text":"...","source":"simplewiki","url":"...","metadata":{"lang":"en"}}
```

| Field | Required | Notes |
|-------|----------|-------|
| `text` | yes | Primary body (alias: `content`) |
| `id` | no | Stable document id when provided |
| `title` | no | Defaults to line number label |
| `source` | no | Provenance string |
| `url` | no | Stored in metadata |
| `metadata` | no | Must be JSON-serializable |

Malformed non-blank records fail with the source line number. Default behavior stops the run.

Example preparation (SimpleWiki dump):

```bash
# Normalize a local pages-articles dump to canonical JSONL (Slice 52)
ark corpus prepare-wikipedia /srv/ark-pi/data/sources/simplewiki-latest-pages-articles.xml.bz2 \
  --output /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --project simplewiki \
  --checksum-file /srv/ark-pi/data/sources/simplewiki-latest-sha1sums.txt

# Ingest the prepared JSONL
ark corpus ingest /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki \
  --batch-size 100
```

See [wikipedia-corpus.md](wikipedia-corpus.md) for dump acquisition, checksum verification, resume behavior, and wikitext cleaning limits.

Legacy manual normalization (external tooling):

```bash
jq -c '{id:.page_id|tostring, title:.title, text:.text, source:"simplewiki"}' \
  dump.ndjson > /srv/ark-pi/data/sources/simplewiki.jsonl
```

### Text directory

- Recursively reads `*.txt` files under the source root
- Stable lexical path ordering
- Document identity from relative path + content digest
- Does not follow symlinks outside the source root
- Unreadable files fail with a clear path

PDF, EPUB, HTML, XML dumps, and compressed archives are out of scope for corpus ingest itself. Normalize Wikimedia XML dumps with `ark corpus prepare-wikipedia` (see [wikipedia-corpus.md](wikipedia-corpus.md)) or other separate preparation tooling.

## Run layout

Run state lives under the configured workspace (never under the git checkout):

```
$ARK_WORKSPACE_DIR/corpus-runs/<run-id>/
  manifest.json
  checkpoint.json
  completion.sqlite
  errors.jsonl
  summary.json
```

The destination index is written under `$ARK_WORKSPACE_DIR/indexes/<slug>/`.

Run id (default) is derived from source fingerprint, destination index, chunking configuration, and backend. Override with `--run-id ID`.

## Checkpoints and resume

Checkpoint schema: `ark-pi-corpus-checkpoint` version 1.

Resume binds:

- source fingerprint (content hash, not mtime alone)
- destination index slug
- chunking configuration
- index backend

Resume only with `--resume`. Mismatched source or configuration fails with an actionable message. Use `--force-rebuild --yes` to discard the selected run and index.

Completed document ids are tracked in `completion.sqlite` (not unbounded in `checkpoint.json`). Resume skips completed documents and avoids duplicate chunks.

If document content changes after completion, re-ingest requires `--force-rebuild --yes`.

## Batching

`--batch-size N` controls documents per batch (default 100). Checkpoint updates occur only after a batch is durably written to the index and completion ledger.

## Error policy

Default: stop on first document error.

With `--continue-on-error`:

- Failed documents are recorded in `errors.jsonl` (sanitized; no full document body)
- Ingestion continues
- Exit code 2 when failures occurred

## Power loss expectations

- Graceful interrupt (`Ctrl+C`, SIGTERM when supported): checkpoint marked `interrupted`, completed batches preserved, exact resume command printed
- Hard kill / power loss during an in-flight batch: the batch may be partially written; chunk id deduplication and the completion ledger prevent duplicate catalog entries on resume, but operators should inspect status after unclean shutdown
- SIGKILL and kernel termination are not caught falsely

## Fingerprint cost

JSONL fingerprinting streams a full-file SHA-256 (multi-GB files can take minutes). Directory fingerprinting hashes every `.txt` file. Use `--dry-run` to preview the plan without writes.

## Flags reference

| Flag | Purpose |
|------|---------|
| `--index` | Destination workspace index slug (required) |
| `--workspace-dir` | Override `ARK_WORKSPACE_DIR` |
| `--batch-size` | Documents per batch |
| `--chunk-size` / `--chunk-overlap` | Chunking parameters |
| `--backend` | `simple` required; Chroma rejected for corpus ingest |
| `--resume` | Continue from checkpoint |
| `--run-id` | Override derived run id |
| `--force-rebuild` | Delete run state + target index (`--yes` required) |
| `--dry-run` | Fingerprint and plan only |
| `--continue-on-error` | Log failures and continue |
| `--json` | Machine-readable result on stdout |

## Architecture note

Corpus ingest logic lives in `ark_pi.corpus` (service layer). The CLI is a thin adapter. No long-running HTTP endpoint is provided in this slice; future job orchestration may call the same service functions.
