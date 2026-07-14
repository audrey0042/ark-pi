# Wikipedia corpus preparation

Offline normalization of local Wikimedia **pages-articles** XML dumps into canonical JSONL for [corpus ingest](corpus-ingest.md). Download, preparation, and ingestion are separate stages. The LLM Pi is not required for any of them.

## Supported dump type

- **Format:** MediaWiki XML export (`pages-articles` / current-content dumps)
- **Compression:** `.xml`, `.xml.gz`, or `.xml.bz2` (magic-byte detection with suffix fallback)
- **Not supported:** `.7z`, SQL dumps, multistream index files, revision-history-only dumps

Obtain dumps manually from [Wikimedia dumps](https://dumps.wikimedia.org/simplewiki/latest/) (operator-controlled; no network access from Ark Pi preparation).

Example files:

```text
simplewiki-latest-pages-articles.xml.bz2
simplewiki-latest-sha1sums.txt
```

## Three-stage workflow

```bash
# 1. Download (operator workstation; outside Ark Pi)
mkdir -p ~/ark-corpora/simplewiki && cd ~/ark-corpora/simplewiki
curl -fLO https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-pages-articles.xml.bz2
curl -fLO https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-sha1sums.txt

# 2. Prepare (offline normalization to JSONL)
ark corpus prepare-wikipedia simplewiki-latest-pages-articles.xml.bz2 \
  --output /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --project simplewiki \
  --source-url https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-pages-articles.xml.bz2 \
  --checksum-file simplewiki-latest-sha1sums.txt

# 3. Ingest (Slice 51 resumable bulk load)
ark corpus ingest /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki \
  --batch-size 100
```

## CLI command

```bash
ark corpus prepare-wikipedia INPUT --output PATH [options]
```

### Common flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--output PATH` | required | Final canonical JSONL path |
| `--project NAME` | `simplewiki` | Source identifier in records and manifest |
| `--base-url URL` | `https://simple.wikipedia.org/wiki/` | Article URL prefix |
| `--namespace N` | `0` (repeatable) | Include only selected namespaces |
| `--min-text-chars N` | `100` | Skip short normalized articles |
| `--limit N` | none | Stop after N emitted records (samples/tests) |
| `--resume` | false | Continue a compatible interrupted run |
| `--force --yes` | false | Replace existing output and sidecars |
| `--checkpoint-every N` | `1000` | Persist state every N scanned pages |
| `--continue-on-page-error` | false | Log sanitized page errors and continue |
| `--dry-run` | false | Validate and print plan only |
| `--json` | false | Machine-readable summary on stdout |
| `--checksum-file PATH` | none | Wikimedia `hash filename` list |
| `--expected-sha1/sha256` | none | Verify compressed dump checksum |

Exit codes: **0** success, **1** fatal error, **2** interrupted or partial (page errors with `--continue-on-page-error`).

## Output schema

One compact JSON object per line:

```json
{
  "id": "simplewiki:page:12345",
  "title": "Example article",
  "text": "Normalized plain article text.",
  "source": "simplewiki",
  "url": "https://simple.wikipedia.org/wiki/Example_article",
  "metadata": {
    "page_id": 12345,
    "revision_id": 67890,
    "revision_timestamp": "2026-07-01T12:34:56Z",
    "revision_sha1": "example",
    "namespace": 0,
    "redirect": false,
    "redirect_target": null,
    "dump_file": "simplewiki-latest-pages-articles.xml.bz2",
    "normalizer": "ark-pi-wikipedia-v1"
  }
}
```

Prepared JSONL passes `ark corpus ingest` unchanged. Records are **backend-neutral**: the same JSONL feeds lexical `simple` indexes (default) or semantic Chroma indexes (`--backend chroma`). See [corpus-ingest.md](corpus-ingest.md) and [embeddings.md](embeddings.md).

```bash
# Lexical (default)
ark corpus ingest /srv/ark-pi/data/sources/simplewiki-articles.jsonl --index simplewiki

# Semantic smoke test with mock embedder (no torch)
ark corpus ingest /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki-semantic --backend chroma --batch-size 100
```

## Sidecar files

Derived from `--output PATH`:

```text
<output>.partial                 # in-progress JSONL (never use as final)
<output>.checkpoint.json         # resumable preparation state
<output>.errors.jsonl            # sanitized page errors
<output>.manifest.json           # deterministic corpus manifest
<output>.ATTRIBUTION.txt         # operator attribution notice
```

## Checksum verification

Wikimedia publishes SHA-1 sums for dump files. Use `--checksum-file` to match the input basename, or pass `--expected-sha1` / `--expected-sha256` directly. SHA-1 matches Wikimedia metadata; SHA-256 is used for preparation fingerprints. A checksum mismatch is fatal and leaves partial output available for inspection.

## Resume behavior

Preparation supports safe interruption and resume:

- Validates input fingerprint (path, size, SHA-256) and all preparation options
- Repairs incomplete final partial JSONL lines before continuing
- **Sequential rescan:** compressed dumps are read from the beginning; already-scanned pages are skipped by page index. There is no random-access multistream resume in this slice.
- Does not append duplicate emitted records

Incompatible checkpoint changes (input file, project, namespaces, redirect policy, min text length, normalizer version, output path) require `--force --yes`.

## Wikitext cleaning (`ark-pi-wikipedia-v1`)

Deterministic retrieval text, not pixel-perfect MediaWiki rendering:

- **Preserves:** prose, section headings, list text, internal/external link labels
- **Removes:** templates (balanced scan), tables, refs, galleries, math, categories, file/image links, HTML comments
- **Does not:** expand templates, run Lua modules, or invoke a MediaWiki server

Malformed markup is bounded; pathological pages cannot consume unbounded memory or CPU.

## Provenance and attribution

Each record preserves title, page id, revision id, timestamp, and article URL. The manifest records dump checksums and preparation counters. `<output>.ATTRIBUTION.txt` summarizes source project, dump URL/date, and license notice URL.

Ark Pi software licensing does not relicense Wikipedia content. Redistributed prepared corpora must preserve applicable Wikimedia attribution and licensing. See the source project's copyright page (for Simple English Wikipedia: https://simple.wikipedia.org/wiki/Wikipedia:Copyrights).

## Disk space and time

Full SimpleWiki dumps are hundreds of megabytes compressed and several gigabytes prepared. Allow ample disk space on the preparation host (`/srv/ark-pi/data/sources/` on ark-rag). Preparation may take hours on a Pi; the LLM Pi is not involved.

## See also

- [corpus-ingest.md](corpus-ingest.md) — ingest prepared JSONL
- [architecture.md](architecture.md) — preparation vs ingestion boundary
