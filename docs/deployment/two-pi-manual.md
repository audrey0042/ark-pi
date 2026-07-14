# Two-Pi manual deployment

How to stand up **ark-rag** and **ark-llm** by hand using the CLI and deploy commands in this repo.

Use case: index your own docs on ark-rag, run llama.cpp on ark-llm, ask questions with no WAN (e.g. *"how do I purify water?"*).

Laptop-only smoke test first: [README quickstart](../../README.md#quickstart).

This is manual steps, not an installer. I haven't run the full stack end-to-end on real Pi hardware from this repo. Paths and systemd snippets are examples to edit.

`install.sh` can install base OS prerequisites on apt-based hosts (Raspberry Pi OS, Debian, Ubuntu), bootstrap the app, optionally build llama.cpp with `--llama-build`, render templates, validate the result (`--validate-only` or automatic post-install validation), and with `--install-services` install generated env/systemd files (use `--service-root /tmp/...` to review without touching real `/etc`). Use `--no-os-packages` when packages are already installed. GGUF model download and network setup remain manual.

## What the CLI does and doesn't do

| CLI | Does not |
|-----|----------|
| Render env/systemd templates | Install systemd units |
| Dry-run preflight + install plan | Copy into `/etc`, `/opt`, `/srv` |
| Bundle / verify / unpack to staging | `sudo`, `systemctl`, network config |
| Init, ingest, index, `ark serve` | Install llama.cpp or fetch models |
| Mock LLM tests | Prove WiFi AP or Ethernet works |

Run ark-rag with `ARK_LLM_BACKEND=mock` before ark-llm exists.

Examples that touch `/etc/ark-pi/` or `/opt/ark-pi/` are for you to run manually if you want them. Don't commit bundles, models, or secrets.

## Roles

| Host | Owns | Doesn't own |
|------|------|-------------|
| **ark-rag** | UI, API, catalog, ingest, indexes, prompts, LLM client | Models, llama.cpp |
| **ark-llm** | llama.cpp server, GGUF files | Docs, indexes, WiFi, UI |

ark-llm stays stateless on purpose. Indexes and prompts live on ark-rag. ark-llm just runs the model.

## Assumptions

- Two hosts named `ark-rag` and `ark-llm`, or equivalent fixed IPs / mDNS names (examples use `ark-rag.local` and `ark-llm.local`).
- **Python ≥ 3.12** (see `pyproject.toml`).
- Git available on both hosts to clone this repository.
- Chroma not required; default is `simple` lexical index
- **Mock LLM backend** is the default for local smoke tests (`ARK_LLM_BACKEND=mock`).
- A **GGUF model file** is required only for the real ark-llm inference path.
- Network between ark-rag and ark-llm is reachable on the configured LLM port (default `8080` in generated templates).
- Hostname discovery (mDNS) is not implemented yet; use explicit IPs or hostnames you control (DHCP reservations, static IPs, or `/etc/hosts`).

## IP-based two-Pi setup (installer)

When ark-rag and ark-llm have fixed LAN addresses, configure the partner LLM URL during RAG Pi install instead of editing `/etc/ark-pi/ark-rag.env` by hand.

Example addresses (substitute your own):

| Host | Example IP | Service |
|------|------------|---------|
| ark-rag | `10.255.255.100` | `ark-rag.service` on port 8000 |
| ark-llm | `10.255.255.101` | `ark-llm.service` on port 8080 |

**LLM Pi** (build, model, services):

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- \
  --role llm --install-services --llama-build --download-model --yes
```

**RAG Pi** with explicit partner address:

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- \
  --role rag --install-services --llm-base-url http://10.255.255.101:8080 --yes
```

Convenience alias (`10.255.255.101` becomes `http://10.255.255.101:8080`):

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- \
  --role rag --install-services --partner-ip 10.255.255.101 --yes
```

Dry-run to review the plan (shows **Partner LLM URL**):

```bash
sh install.sh --role rag --llm-base-url http://10.255.255.101:8080 --dry-run
```

Default when no flag is provided: `ARK_LLM_BASE_URL=http://ark-llm.local:8080`.

Verify after install:

```bash
sudo systemctl restart ark-rag.service
curl -s http://127.0.0.1:8000/api/status | jq .paths.llm_base_url
sudo /opt/ark-pi/.venv/bin/ark appliance smoke --env-file /etc/ark-pi/ark-rag.env
sudo /opt/ark-pi/.venv/bin/ark appliance ask-smoke --env-file /etc/ark-pi/ark-rag.env
sudo /opt/ark-pi/.venv/bin/ark appliance ask-smoke --env-file /etc/ark-pi/ark-rag.env --json
```

`ark appliance ask-smoke` uses an isolated tiny corpus (`ark-pi-smoke-beacon.txt` → `ark-smoke` index) with a deterministic beacon phrase (`copper lantern`). It validates ingest, chunking, indexing, retrieval, prompt assembly, and LLM generation through the configured partner backend. Artifacts are removed after the run unless you pass `--keep`.

Capture an offline validation receipt after basic checks:

```bash
sudo /opt/ark-pi/.venv/bin/ark appliance receipt --env-file /etc/ark-pi/ark-rag.env --output /tmp/ark-rag-receipt.json
```

### Optional RAG Pi embedding runtime probe

Embedding diagnostics are optional and do not involve the LLM Pi. Default backend is `mock` (no ML dependencies). To probe a real local model after copying artifacts to `/srv/ark-pi/embedding-models/`:

```bash
python3 --version
uname -m
sudo /opt/ark-pi/.venv/bin/ark embeddings status --env-file /etc/ark-pi/ark-rag.env --json
cd /opt/ark-pi && /opt/ark-pi/.venv/bin/python -m pip install -e '.[embeddings]'
sudo /opt/ark-pi/.venv/bin/ark embeddings test --env-file /etc/ark-pi/ark-rag.env --json
sudo /opt/ark-pi/.venv/bin/ark embeddings evaluate --env-file /etc/ark-pi/ark-rag.env --json
```

See [embeddings.md](../embeddings.md) for model preparation, configuration, and expected failure modes.

For a receipt that includes active smoke results (opt-in network and LLM activity):

```bash
sudo /opt/ark-pi/.venv/bin/ark appliance receipt \
  --env-file /etc/ark-pi/ark-rag.env \
  --run-smoke \
  --run-ask-smoke \
  --output /tmp/ark-rag-active-receipt.json
```

Raw LLM server fallback for debugging (bypasses ark-pi):

```bash
curl -s http://192.168.1.134:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"local","messages":[{"role":"user","content":"Reply with: ark-pi-ok"}]}'
```

Auto-discovery (mDNS, LAN scan) is future work. Until then, ensure both Pis have stable addresses via your router (DHCP reservations) or OS static IP configuration.

## RAG Pi OS prerequisites

The first observed RAG Pi target is **Raspberry Pi 5 / Debian 13 trixie (aarch64)**. On apt-based Debian-family hosts, `install.sh` can install this baseline before app bootstrap:

`ca-certificates`, `curl`, `git`, `python3`, `python3-venv`, `python3-pip`, `python3-dev`, `build-essential`, `pkg-config`, `rsync`, `unzip`, `jq`

Plan what would be installed (no host changes):

```bash
sh install.sh --role rag --dry-run
```

If packages are already present, skip apt and verify commands only:

```bash
sh install.sh --role rag --no-os-packages --dry-run
```

Optional `install.sh --llama-build` automates llama.cpp source build; GGUF model placement and network/WiFi setup remain manual on ark-llm and are documented below.

On a sudo-capable user account, `install.sh` can prepare default `/opt/ark-pi` and `/srv/ark-pi` automatically (sudo `mkdir` + leaf `chown` to the invoking user). git, venv, pip, and deploy render still run unprivileged:

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role rag --install-services --yes
```

Do not pipe the whole installer through `sudo` unless you want a root-owned checkout.

## First smoke (any machine)

Run on a laptop or either Pi before systemd or llama.cpp.

```bash
git clone <your-ark-pi-repo-url>
cd ark-pi
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

python -m pytest -v
ark quickstart --force
ark preflight
ark serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` and confirm the web UI loads. Stop the server with Ctrl+C when done.

## Deployment artifacts

Render templates and zip them for review. **Does not install anything.**

Neutral placeholder paths below (dev smoke example — not appliance defaults). Replace with directories on your machine, or use `deploy/generated` for local review.

```bash
source .venv/bin/activate

ark deploy render --output-dir /path/to/deploy-render --force
ark deploy preflight --generated-dir /path/to/deploy-render
ark deploy plan --generated-dir /path/to/deploy-render
ark deploy bundle --generated-dir /path/to/deploy-render --output /path/to/deploy-bundle.zip --force
ark deploy verify-bundle --bundle /path/to/deploy-bundle.zip
```

### Generated files (review material)

| File | Role | Purpose |
|------|------|---------|
| `ark-rag.env` | ark-rag | Example environment for `ark serve` |
| `ark-rag.service` | ark-rag | Example systemd unit |
| `ark-llm.env` | ark-llm | Example llama.cpp paths and ports |
| `ark-llm.service` | ark-llm | Example systemd unit |

The zip is portable. Verification reads the archive in memory; it doesn't extract or install.

Missing `/opt/ark-pi/.venv/bin/ark`, llama.cpp, or model paths on a laptop is normal before Pi install.

## Unpack a verified bundle for review

After verify passes, unpack to a staging dir and look at the files. Staging is not install.

```bash
ark deploy verify-bundle --bundle /path/to/deploy-bundle.zip
ark deploy unpack-bundle \
  --bundle /path/to/deploy-bundle.zip \
  --staging-dir /path/to/deploy-staging \
  --force

find /path/to/deploy-staging -maxdepth 3 -type f -print | sort
```

Expected layout under staging:

```text
README.txt
manifest.json
templates/ark-rag.env
templates/ark-rag.service
templates/ark-llm.env
templates/ark-llm.service
reports/deployment-preflight.json
reports/deployment-plan.json
reports/deployment-plan.md
```

Read `reports/deployment-plan.md` for the full dry-run install plan. Ark Pi does not execute those steps.

## Manual ark-rag setup

### 1. Review generated templates

From staging or `deploy/generated/`, read:

- `templates/ark-rag.env`: workspace paths, index backend, LLM settings
- `templates/ark-rag.service`: example `ExecStart` for `ark serve`

Adapt paths if your layout differs from `/opt/ark-pi` and `/srv/ark-pi/`.

### 2. Choose LLM backend for first boot

| Phase | `ARK_LLM_BACKEND` | `ARK_LLM_BASE_URL` |
|-------|-------------------|--------------------|
| First boot | `mock` | not required |
| After ark-llm is ready | `openai-compatible` | `http://ark-llm.local:8080` (or your ark-llm IP) |

Generated templates default to `openai-compatible` pointing at ark-llm. For first boot, set `mock` in your local `.env` or exported environment until ark-llm is verified.

### 3. Install project and prepare storage

Example layout (adjust to your disk mounts):

```bash
# You run this manually when not using install.sh path prep
sudo mkdir -p /opt/ark-pi /srv/ark-pi/data/workspace /srv/ark-pi/data/sources
sudo chown "$USER":"$USER" /opt/ark-pi /srv/ark-pi/data/workspace /srv/ark-pi/data/sources
```

Or use `install.sh --role rag --yes` to prepare `/opt/ark-pi` and `/srv/ark-pi` with sudo and bootstrap the app.

```bash
# Manual clone path (when not using install.sh)
cd /opt/ark-pi
git clone <your-ark-pi-repo-url> .
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set environment variables to match your paths (or copy/adapt `ark-rag.env` manually):

```bash
export ARK_WORKSPACE_DIR=/srv/ark-pi/data/workspace
export ARK_SOURCE_DIR=/srv/ark-pi/data/sources
export ARK_INDEX_BACKEND=simple
export ARK_LLM_BACKEND=mock   # switch to openai-compatible later
```

### 4. Initialize and smoke-test ark-rag

```bash
source /opt/ark-pi/.venv/bin/activate

ark init --sample
ark preflight
ark quickstart --force
ark llm status
ark serve --host 0.0.0.0 --port 8000
```

Confirm the web UI and API respond from another machine on your network. **Do not enable systemd until a manual foreground run works.**

Stop with Ctrl+C, then proceed to systemd review (below) when ready.

### 5. Load a reference corpus (RAG Pi only)

Corpus **preparation** and **ingestion** run on ark-rag only; ark-llm is not required. For SimpleWiki, download the dump on a workstation (or directly on ark-rag), normalize it offline, then ingest the prepared JSONL.

**Disk space and time:** full SimpleWiki dumps are large (hundreds of MB compressed, several GB prepared). Allow ample space under `/srv/ark-pi/data/sources/` and expect preparation to take hours on a Pi.

```bash
# Download (operator-controlled; example)
mkdir -p /srv/ark-pi/data/sources/simplewiki && cd /srv/ark-pi/data/sources/simplewiki
curl -fLO https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-pages-articles.xml.bz2
curl -fLO https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-sha1sums.txt

# Prepare: normalize XML dump to canonical JSONL (offline; no LLM Pi)
sudo /opt/ark-pi/.venv/bin/ark corpus prepare-wikipedia \
  simplewiki-latest-pages-articles.xml.bz2 \
  --output /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --project simplewiki \
  --source-url https://dumps.wikimedia.org/simplewiki/latest/simplewiki-latest-pages-articles.xml.bz2 \
  --checksum-file simplewiki-latest-sha1sums.txt

# Resume preparation after interrupt
sudo /opt/ark-pi/.venv/bin/ark corpus prepare-wikipedia \
  simplewiki-latest-pages-articles.xml.bz2 \
  --output /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --resume

# Ingest prepared JSONL into a named workspace index
sudo /opt/ark-pi/.venv/bin/ark corpus ingest \
  /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki \
  --batch-size 100 \
  --dry-run

sudo /opt/ark-pi/.venv/bin/ark corpus ingest \
  /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki \
  --batch-size 100

sudo /opt/ark-pi/.venv/bin/ark corpus status --json

# Resume ingest after interrupt or power loss (graceful stop)
sudo /opt/ark-pi/.venv/bin/ark corpus ingest \
  /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki \
  --batch-size 100 \
  --resume

# Optional: semantic Chroma index (mock embedder smoke test; install '.[chroma]' for real Chroma)
sudo /opt/ark-pi/.venv/bin/ark corpus ingest \
  /srv/ark-pi/data/sources/simplewiki-articles.jsonl \
  --index simplewiki-semantic \
  --backend chroma \
  --batch-size 100 \
  --json
```

Preparation sidecars (`.partial`, `.checkpoint.json`, `.manifest.json`, `.ATTRIBUTION.txt`) live next to the output JSONL. Ingest checkpoints live under `$ARK_WORKSPACE_DIR/corpus-runs/`. See [wikipedia-corpus.md](../wikipedia-corpus.md) and [corpus-ingest.md](../corpus-ingest.md).

## Manual ark-llm setup

### 1. Review generated templates

From staging or `deploy/generated/`:

- `templates/ark-llm.env`: binary path, model path, host, port
- `templates/ark-llm.service`: example unit file

### 2. Build llama.cpp (optional automation)

`install.sh` can clone and build llama.cpp when you pass `--llama-build` (role `llm` or `both`):

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- \
  --role llm --llama-build --install-services --yes
```

Re-running the installer on an existing `/opt/ark-pi` git checkout fast-forwards to `origin/main` before `pip install -e`. Uncommitted local edits under `/opt/ark-pi` cause a clear failure instead of being overwritten.

If a previous failed `--llama-build` left only `vendor/` under `/opt/ark-pi` (old default location), inspect and remove it before rerunning:

```bash
cd /opt/ark-pi && git status --short
# if only ?? vendor/ appears:
rm -rf /opt/ark-pi/vendor
```

Default paths (`/opt/ark-pi` is app source only; llama.cpp build artifacts live under the data dir):

- Source: `/srv/ark-pi/vendor/llama.cpp`
- Binary: `/srv/ark-pi/vendor/llama.cpp/build/bin/llama-server` (`ARK_LLAMA_BIN` in `ark-llm.env`)
- Configure: `cmake -S /srv/ark-pi/vendor/llama.cpp -B /srv/ark-pi/vendor/llama.cpp/build` (installer passes `-S` explicitly)

You can still build manually under another path; ensure `ARK_LLAMA_BIN` in your env file matches.

### 3. Place or download a GGUF model

**Option A — installer download (opt-in):**

```bash
# Plan first (no network)
sh install.sh --role llm --download-model --dry-run

# Build llama.cpp, download model, install services (common full path)
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | \
  sh -s -- --role llm --install-services --llama-build --download-model --no-start --yes

# Download only (separate from llama build)
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | \
  sh -s -- --role llm --install-services --download-model --no-start --yes

# Advanced 8B preset (explicit; ~5 GB; may be tight on Pi 5 8GB)
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | \
  sh -s -- --role llm --install-services --download-model --model-preset qwen3-8b-q4km --no-start --yes
```

Downloads verify SHA256 and install atomically to `/srv/ark-pi/models/model.gguf`. Default installs do **not** download unless `--download-model` is passed. Downloading a model does not build `llama-server`; `--llama-build` and `--download-model` remain independent.

**Option B — manual placement:**

Copy a GGUF model to the configured path (generated default: `/srv/ark-pi/models/model.gguf`). Models stay out of git.

`ark-llm.service` starts only when **both** the GGUF file and an executable `llama-server` binary exist. If you install services before both are ready, the unit is enabled but not started. After the model **and** binary are present:

```bash
sudo systemctl start ark-llm.service
sudo systemctl status ark-llm.service --no-pager
```

### 4. Run the server manually first

Load variables from your adapted `ark-llm.env`, then start the server in the foreground:

```bash
# Check --help on your binary; flag names can drift between llama.cpp versions
$ARK_LLAMA_BIN \
  --host 0.0.0.0 \
  --port 8080 \
  --model /srv/ark-pi/models/model.gguf \
  --ctx-size 4096 \
  --threads 4
```

**Do not enable systemd on ark-llm until manual foreground run works.**

## Connect ark-rag to ark-llm

When ark-llm responds manually, ark-rag needs `ARK_LLM_BACKEND=openai-compatible` and a reachable `ARK_LLM_BASE_URL`.

**Preferred (installer):** set the partner address at RAG Pi install time:

```bash
sh install.sh --role rag --install-services --llm-base-url http://10.255.255.101:8080 --yes
# or: --partner-ip 10.255.255.101
```

**Manual fallback:** edit `/etc/ark-pi/ark-rag.env` and set `ARK_LLM_BASE_URL` to the hostname or IP you actually use, then restart `ark-rag.service`.

### Status vs test

```bash
# Config only; no call to ark-llm
ark llm status

# Actually hits the backend
ark llm test --llm-backend openai-compatible --llm-base-url http://ark-llm.local:8080
```

`ark llm status` does not prove ark-llm is reachable. Use `ark llm test` when you want a real request.

Mock smoke (no ark-llm required):

```bash
ark llm test --llm-backend mock
```

## Manual systemd review

Generated templates and the install plan show where files would go:

| Artifact | Copy to (you run this) |
|----------|-----------------------------------|
| `ark-rag.env` | `/etc/ark-pi/ark-rag.env` |
| `ark-rag.service` | `/etc/systemd/system/ark-rag.service` |
| `ark-llm.env` | `/etc/ark-pi/ark-llm.env` |
| `ark-llm.service` | `/etc/systemd/system/ark-llm.service` |

Review the dry-run plan:

```bash
ark deploy plan --generated-dir deploy/generated --format markdown
```

The plan lists manual steps (`sudo mkdir`, `sudo cp`, `systemctl`, etc.). **The CLI never runs them.** You do, after foreground testing works.

Example for ark-rag (review before running):

```bash
sudo cp templates/ark-rag.env /etc/ark-pi/ark-rag.env
sudo cp templates/ark-rag.service /etc/systemd/system/ark-rag.service
sudo systemctl daemon-reload
sudo systemctl enable --now ark-rag.service
sudo systemctl status ark-rag.service
```

Repeat analogous steps for ark-llm on the LLM host.

## Validation checklist

Run on **ark-rag** (installed env is `/etc/ark-pi/ark-rag.env`, `root:root` mode `0640`; load it with sudo so CLI checks match `ark-rag.service`):

```bash
sudo sh -c 'set -a; . /etc/ark-pi/ark-rag.env; set +a; exec /opt/ark-pi/.venv/bin/ark preflight'
sudo sh -c 'set -a; . /etc/ark-pi/ark-rag.env; set +a; exec /opt/ark-pi/.venv/bin/ark deploy preflight --generated-dir /srv/ark-pi/deploy/generated --role rag'
sudo sh -c 'set -a; . /etc/ark-pi/ark-rag.env; set +a; exec /opt/ark-pi/.venv/bin/ark llm status'
/opt/ark-pi/.venv/bin/ark llm test --llm-backend mock
curl http://ark-rag.local:8000/healthz
curl http://ark-rag.local:8000/api/status
```

Bare `ark preflight` without loading `/etc/ark-pi/ark-rag.env` uses default config paths, not the service environment.

Run on **ark-llm** (installed env is `/etc/ark-pi/ark-llm.env`):

```bash
sudo sh -c 'set -a; . /etc/ark-pi/ark-llm.env; set +a; exec /opt/ark-pi/.venv/bin/ark preflight'
sudo systemctl status ark-llm.service --no-pager
ls -l /srv/ark-pi/vendor/llama.cpp/build/bin/llama-server
ls -l /srv/ark-pi/models/model.gguf
```

When ark-llm responds (from ark-rag):

## Troubleshooting

| Symptom | Things to check |
|---------|-----------------|
| ark-rag web UI not reachable | `ark serve` binding (`ARK_HOST`, `--host`); firewall; WiFi/Ethernet not configured yet |
| `ark llm status` looks fine but active test fails | Wrong `ARK_LLM_BASE_URL`; ark-llm not running; firewall between Pis; DNS for `ark-llm.local` |
| Model path missing on ark-llm | GGUF file at `ARK_MODEL_PATH` (default `/srv/ark-pi/models/model.gguf`); permissions; disk mount at `/srv/ark-pi/models` |
| Deployment preflight warnings on laptop | Normal. `/opt/ark-pi` and model paths won't exist until install |
| Workspace/source dirs missing | Run `ark init --sample` or create paths manually; check `ARK_WORKSPACE_DIR` and `ARK_SOURCE_DIR` |
| Wrong hostname or DNS | Use fixed IPs in `ARK_LLM_BASE_URL` temporarily; add `/etc/hosts` entries on ark-rag |
| Network isolation | Ethernet link between Pis; routes; no cross-VLAN blocking between ark-rag and ark-llm |

## What is still future work

- llama.cpp install, model setup, network/WiFi ([installer-bootstrap-contract.md](installer-bootstrap-contract.md)); `--install-services` handles env/systemd copy when explicitly requested
- WiFi AP mode on ark-rag
- Network configuration (static Ethernet, DHCP, DNS, firewall)
- llama.cpp install automation
- Model download and management
- Authentication
- Semantic search and hybrid retrieval over Chroma indexes (Slice 8)
- Hardware-specific performance tuning

See [roadmap.md](../roadmap.md) for staged development status.
