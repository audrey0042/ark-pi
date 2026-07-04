# Two-Pi manual deployment

How to stand up **ark-rag** and **ark-llm** by hand using the CLI and deploy commands in this repo.

Use case: index your own docs on ark-rag, run llama.cpp on ark-llm, ask questions with no WAN (e.g. *"how do I purify water?"*).

Laptop-only smoke test first: [README quickstart](../../README.md#quickstart).

This is manual steps, not an installer. I haven't run the full stack end-to-end on real Pi hardware from this repo. Paths and systemd snippets are examples to edit.

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

`/tmp` paths match the [README examples](../../README.md#deployment-artifacts). For local dev you can use `deploy/generated` instead.

```bash
source .venv/bin/activate

ark deploy render --output-dir /tmp/ark-pi-deploy-render --force
ark deploy preflight --generated-dir /tmp/ark-pi-deploy-render
ark deploy plan --generated-dir /tmp/ark-pi-deploy-render
ark deploy bundle --generated-dir /tmp/ark-pi-deploy-render --output /tmp/ark-pi-deploy-bundle.zip --force
ark deploy verify-bundle --bundle /tmp/ark-pi-deploy-bundle.zip
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
# You run this; the CLI does not
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

- `templates/ark-llm.env`: binary path, model path, host, port
- `templates/ark-llm.service`: example unit file

### 2. Install llama.cpp manually

Ark Pi does **not** install llama.cpp. Build or install it on ark-llm outside this automation, for example under `/opt/llama.cpp/`. See upstream llama.cpp documentation for Pi/aarch64 build steps.

Ensure the server binary path matches `ARK_LLAMACPP_SERVER_BIN` in your env file (generated default: `/opt/llama.cpp/llama-server`).

### 3. Place a GGUF model

Copy a GGUF model to the configured path (generated default: `/srv/ark-pi/models/model.gguf`). Models stay out of git.

### 4. Run the server manually first

Load variables from your adapted `ark-llm.env`, then start the server in the foreground:

```bash
# Flags vary by llama.cpp build; check --help on your binary
$ARK_LLAMACPP_SERVER_BIN \
  --host 0.0.0.0 \
  --port 8080 \
  --model /srv/ark-pi/models/model.gguf \
  --ctx-size 4096 \
  --threads 4
```

Check your binary's `--help`. Flag names change between llama.cpp versions.

**Do not enable systemd on ark-llm until manual foreground run works.**

## Connect ark-rag to ark-llm

When ark-llm responds manually:

1. On **ark-rag**, set:
   - `ARK_LLM_BACKEND=openai-compatible`
   - `ARK_LLM_BASE_URL=http://ark-llm.local:8080` (hostname or IP you actually use)
2. Restart `ark serve` (foreground) or reload env for your process manager.

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

HTTP examples (need DNS or `/etc/hosts`):

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
| Deployment preflight warnings on laptop | Normal. `/opt/ark-pi` and model paths won't exist until install |
| Workspace/source dirs missing | Run `ark init --sample` or create paths manually; check `ARK_WORKSPACE_DIR` and `ARK_SOURCE_DIR` |
| Wrong hostname or DNS | Use fixed IPs in `ARK_LLM_BASE_URL` temporarily; add `/etc/hosts` entries on ark-rag |
| Network isolation | Ethernet link between Pis; routes; no cross-VLAN blocking between ark-rag and ark-llm |

## What is still future work

- Installer script ([roadmap §36](../roadmap.md#36-installer-bootstrap)); manual guide is what exists today
- WiFi AP mode on ark-rag
- Network configuration (static Ethernet, DHCP, DNS, firewall)
- llama.cpp install automation
- Model download and management
- Authentication
- Chroma / semantic index production path
- Hardware-specific performance tuning

See [roadmap.md](../roadmap.md) for staged development status.
