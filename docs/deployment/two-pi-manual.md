# Two-Pi Manual Deployment

Practical guide for a human operator setting up **ark-rag** and **ark-llm** from fresh hosts using the existing Ark Pi CLI, deployment artifacts, and diagnostics.

This is a **manual guide**, not an automated installer. Ark Pi has **not** been validated end-to-end on real Raspberry Pi hardware in this repository. Treat paths, hostnames, and systemd examples as **intended** layout for review.

## Status and safety

| What Ark Pi CLI does today | What it does **not** do |
|----------------------------|-------------------------|
| Render reviewable env/systemd templates | Install systemd units |
| Run dry-run deployment preflight and install plans | Copy files into `/etc`, `/opt`, or `/srv` |
| Package, verify, and unpack deployment bundles to staging | Run `sudo`, `systemctl`, or configure networking |
| Initialize workspace storage, ingest, index, and serve the API | Install llama.cpp or download models |
| Mock LLM smoke tests offline | Prove Pi WiFi AP or Ethernet setup |

**Start with mock mode on ark-rag** before connecting to a real ark-llm server. Mock mode validates retrieval, prompt assembly, and client wiring without network calls.

Commands shown for system directories (for example `/etc/ark-pi/`, `/opt/ark-pi/`) are **for human review and manual execution** on the target host. Only run them when you understand the effect.

Do not commit generated deployment bundles, model files, or secrets to git.

## Roles

| Host | Responsibilities | Does **not** own |
|------|------------------|------------------|
| **ark-rag** | Web UI, FastAPI API, workspace catalog, ingest, indexing, prompt assembly, LLM client | Model weights, llama.cpp process |
| **ark-llm** | OpenAI-compatible llama.cpp (or compatible) server, GGUF model files on disk | Documents, indexes, WiFi, web UI |

**Why ark-llm stays mostly stateless:** retrieval needs workspace paths, catalog metadata, and index files on ark-rag. Prompt assembly combines retrieved chunks with the user question on ark-rag. ark-llm receives a complete prompt and returns text — no document state, no session history, no index. That keeps inference memory available for the model and lets you upgrade or replace the LLM host independently.

## Assumptions

- Two hosts named `ark-rag` and `ark-llm`, or equivalent fixed IPs / mDNS names (examples use `ark-rag.local` and `ark-llm.local`).
- **Python ≥ 3.12** (see `pyproject.toml`).
- Git available on both hosts to clone this repository.
- **Chroma not required** for MVP — default index backend is `simple` (lexical).
- **Mock LLM backend** is the default for local smoke tests (`ARK_LLM_BACKEND=mock`).
- A **GGUF model file** is required only for the real ark-llm inference path.
- Network between ark-rag and ark-llm is reachable on the configured LLM port (default `8080` in generated templates).

## Recommended first smoke on any machine

Run this on a laptop or on either Pi **before** touching systemd or llama.cpp. It verifies Ark Pi without Pi-specific hardware and without a real LLM server.

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

## Generate deployment artifacts

On a build machine or either Pi, render templates and package review artifacts. **These commands do not install anything.**

```bash
source .venv/bin/activate

ark deploy render --output-dir deploy/generated --force
ark deploy preflight --generated-dir deploy/generated
ark deploy plan --generated-dir deploy/generated
ark deploy bundle --generated-dir deploy/generated --output /tmp/ark-pi-deploy-bundle.zip --force
ark deploy verify-bundle --bundle /tmp/ark-pi-deploy-bundle.zip
```

### Generated files (review material)

| File | Role | Purpose |
|------|------|---------|
| `ark-rag.env` | ark-rag | Example environment for `ark serve` |
| `ark-rag.service` | ark-rag | Example systemd unit (review only) |
| `ark-llm.env` | ark-llm | Example llama.cpp paths and ports |
| `ark-llm.service` | ark-llm | Example systemd unit (review only) |

The bundle zip is **portable** — copy it to another machine for review. Verification is read-only and does not extract or install.

Warnings about missing `/opt/ark-pi/.venv/bin/ark`, llama.cpp binaries, or model files are **expected on a dev laptop** before Pi install.

## Unpack a verified bundle for review

After verification succeeds, extract into a **staging directory** for human inspection. Staging is not installation.

```bash
ark deploy verify-bundle --bundle /tmp/ark-pi-deploy-bundle.zip
ark deploy unpack-bundle \
  --bundle /tmp/ark-pi-deploy-bundle.zip \
  --staging-dir /tmp/ark-pi-deploy-staging \
  --force

find /tmp/ark-pi-deploy-staging -maxdepth 3 -type f -print | sort
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

- `templates/ark-rag.env` — workspace paths, index backend, LLM client settings
- `templates/ark-rag.service` — intended `ExecStart` for `ark serve`

Adapt paths if your layout differs from `/opt/ark-pi` and `/srv/ark-pi/`.

### 2. Choose LLM backend for first boot

| Phase | `ARK_LLM_BACKEND` | `ARK_LLM_BASE_URL` |
|-------|-------------------|--------------------|
| First boot (recommended) | `mock` | not required |
| After ark-llm is ready | `openai-compatible` | `http://ark-llm.local:8080` (or your ark-llm IP) |

Generated templates default to `openai-compatible` pointing at ark-llm. For first boot, set `mock` in your local `.env` or exported environment until ark-llm is verified.

### 3. Install project and prepare storage

Example layout (adjust to your disk mounts):

```bash
# Human-operated example — not run by Ark Pi CLI
sudo mkdir -p /opt/ark-pi /srv/ark-pi/data/workspace /srv/ark-pi/data/sources
sudo chown "$USER":"$USER" /opt/ark-pi /srv/ark-pi/data/workspace /srv/ark-pi/data/sources

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

## Manual ark-llm setup

### 1. Review generated templates

From staging or `deploy/generated/`:

- `templates/ark-llm.env` — `ARK_LLAMACPP_SERVER_BIN`, model path, host, port
- `templates/ark-llm.service` — intended service command

### 2. Install llama.cpp manually

Ark Pi does **not** install llama.cpp. Build or install it on ark-llm outside this automation, for example under `/opt/llama.cpp/`. See upstream llama.cpp documentation for Pi/aarch64 build steps.

Ensure the server binary path matches `ARK_LLAMACPP_SERVER_BIN` in your env file (generated default: `/opt/llama.cpp/llama-server`).

### 3. Place a GGUF model

Copy a GGUF model to the configured path (generated default: `/srv/ark-pi/models/model.gguf`). Models stay out of git.

### 4. Run the server manually first

Load variables from your adapted `ark-llm.env`, then start the server in the foreground:

```bash
# Example — flags may differ by llama.cpp version; check your binary's --help
$ARK_LLAMACPP_SERVER_BIN \
  --host 0.0.0.0 \
  --port 8080 \
  --model /srv/ark-pi/models/model.gguf \
  --ctx-size 4096 \
  --threads 4
```

Confirm the server exposes an **OpenAI-compatible** HTTP API on the configured port. Exact flag names are not guaranteed across llama.cpp versions — verify against your installed binary.

**Do not enable systemd on ark-llm until manual foreground run works.**

## Connect ark-rag to ark-llm

When ark-llm responds manually:

1. On **ark-rag**, set:
   - `ARK_LLM_BACKEND=openai-compatible`
   - `ARK_LLM_BASE_URL=http://ark-llm.local:8080` (hostname or IP you actually use)
2. Restart `ark serve` (foreground) or reload env for your process manager.

### Passive status vs. active test

```bash
# Passive — reads config only, does NOT contact ark-llm
ark llm status

# Explicit network check — sends a tiny diagnostic prompt
ark llm test --llm-backend openai-compatible --llm-base-url http://ark-llm.local:8080
```

`ark llm status` confirms configuration is present; it does **not** prove ark-llm is reachable. Use `ark llm test` when you are ready for an explicit connectivity check.

Mock smoke (no ark-llm required):

```bash
ark llm test --llm-backend mock
```

## Manual systemd review

Generated templates and the install plan describe **intended** production layout:

| Artifact | Intended destination (human copy) |
|----------|-----------------------------------|
| `ark-rag.env` | `/etc/ark-pi/ark-rag.env` |
| `ark-rag.service` | `/etc/systemd/system/ark-rag.service` |
| `ark-llm.env` | `/etc/ark-pi/ark-llm.env` |
| `ark-llm.service` | `/etc/systemd/system/ark-llm.service` |

Review the dry-run plan:

```bash
ark deploy plan --generated-dir deploy/generated --format markdown
```

The plan lists example manual commands such as `sudo mkdir`, `sudo cp`, `sudo systemctl daemon-reload`, and `sudo systemctl enable --now`. **Ark Pi does not run these commands.** A human operator performs them after manual foreground testing succeeds.

Typical manual sequence (documentation only — run on the target host at your own discretion):

```bash
# Example for ark-rag — review before running
sudo cp templates/ark-rag.env /etc/ark-pi/ark-rag.env
sudo cp templates/ark-rag.service /etc/systemd/system/ark-rag.service
sudo systemctl daemon-reload
sudo systemctl enable --now ark-rag.service
sudo systemctl status ark-rag.service
```

Repeat analogous steps for ark-llm on the LLM host.

## Validation checklist

Run on **ark-rag**:

```bash
ark preflight
ark deploy preflight --generated-dir deploy/generated
ark llm status
ark llm test --llm-backend mock
```

When ark-llm is configured:

```bash
ark llm test --llm-backend openai-compatible --llm-base-url http://ark-llm.local:8080
```

HTTP checks (examples — require working DNS or `/etc/hosts` and network access):

```bash
curl http://ark-rag.local:8000/healthz
curl http://ark-rag.local:8000/api/status
```

On **ark-llm**, confirm the inference server responds on its configured port using your llama.cpp server's health or models endpoint (consult upstream docs).

## Troubleshooting

| Symptom | Things to check |
|---------|-----------------|
| ark-rag web UI not reachable | `ark serve` binding (`ARK_HOST`, `--host`); firewall; WiFi/Ethernet not configured yet |
| `ark llm status` looks fine but active test fails | Wrong `ARK_LLM_BASE_URL`; ark-llm not running; firewall between Pis; DNS for `ark-llm.local` |
| Model path missing on ark-llm | GGUF file at `ARK_LLAMACPP_MODEL_PATH`; permissions; disk mount at `/srv/ark-pi/models` |
| Deployment preflight warnings on laptop | Expected — `/opt/ark-pi`, llama.cpp binary, and model paths do not exist until Pi install |
| Workspace/source dirs missing | Run `ark init --sample` or create paths manually; check `ARK_WORKSPACE_DIR` and `ARK_SOURCE_DIR` |
| Wrong hostname or DNS | Use fixed IPs in `ARK_LLM_BASE_URL` temporarily; add `/etc/hosts` entries on ark-rag |
| Network isolation | Ethernet link between Pis; routes; no cross-VLAN blocking between ark-rag and ark-llm |

## What is still future work

- Real installer and automated deployment
- WiFi AP mode on ark-rag
- Network configuration (static Ethernet, DHCP, DNS, firewall)
- llama.cpp install automation
- Model download and management
- Authentication
- Chroma / semantic index production path
- Hardware-specific performance tuning

See [roadmap.md](../roadmap.md) for staged development status.
