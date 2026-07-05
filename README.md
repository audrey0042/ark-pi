# Ark Pi

Side project: a small offline RAG box for when the internet or power grid is unreliable. Think censorship, blackout, or just no WAN and two Pis on battery.

You connect a phone or laptop to local WiFi, ask something like *"how do I purify water?"*, and get an answer from text you indexed earlier. No cloud, no hosted vector DB, no remote LLM.

Plan is two Raspberry Pis. **ark-rag** holds the index, web UI, and retrieval. **ark-llm** runs llama.cpp. Splitting the work keeps inference RAM on the second box. This repo is code and docs only; your indexes, models, and runtime data stay out of git.

## Status

Early prototype. Laptop + mock LLM works for smoke tests. Two-Pi offline setup is not finished. Output quality depends on what you index. I have not validated medical or safety advice here. Not hardened for hostile networks.

## What works today

On a laptop, offline, mock LLM by default:

- `ark quickstart` (init, sample source, index, mock ask)
- `ark serve` (FastAPI + built-in web UI)
- Text ingest: paste in browser, browser `.txt` import, server-side files under `ARK_SOURCE_DIR`
- Named workspace indexes: list, delete, export, import (CLI, API, UI)
- Mock LLM path; OpenAI-compatible client for hooking up ark-llm later
- `ark llm status` / `ark llm test`
- `ark preflight`
- `ark deploy *` (render, preflight, plan, bundle, verify, unpack). Review/staging only; does not install anything.

Default index is `simple` (lexical). Chroma and embeddings are optional extras. API/UI details: [docs/architecture.md](docs/architecture.md).

## Quickstart

Mock LLM. No Pi, no model download, no network.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

python -m pytest -v
ark quickstart --force
ark serve --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/. Copy `.env.example` to `.env` if you want non-default settings.

## Common commands

| Command | What it does |
|---------|----------------|
| `ark preflight` | Check paths, catalog, backends (no network) |
| `ark init --sample` | Create workspace/source dirs + sample text |
| `ark workspace list` | List workspace indexes |
| `ark llm status` | Show LLM config (no network call) |
| `ark llm test --llm-backend mock` | Hit the mock backend |
| `ark deploy render --output-dir /tmp/ark-pi-deploy-render --force` | Write example env/systemd templates |

Low-level chunk/index debugging: `ark ingest chunk`, `ark index`, `ark ask`. See [docs/architecture.md](docs/architecture.md).

## Two-Pi setup (target)

| Host | Job |
|------|-----|
| **ark-rag** | Web UI, API, ingest, indexes, prompts, LLM client |
| **ark-llm** | llama.cpp + GGUF on disk |

When WAN is down, ark-rag serves the index and calls ark-llm on the LAN. ark-llm is dumb: prompt in, text out.

```text
phone/laptop --WiFi--> ark-rag --Ethernet--> ark-llm
```

Manual steps: [docs/deployment/two-pi-manual.md](docs/deployment/two-pi-manual.md). WiFi AP, network config, and systemd are still manual/TODO.

## Install bootstrap (`install.sh`)

`install.sh` bootstraps the app and renders deployment templates: on apt-based Debian-family hosts (Raspberry Pi OS, Debian, Ubuntu) it can install the RAG Pi OS prerequisite baseline (`ca-certificates`, `curl`, `git`, `python3`, `python3-venv`, `python3-pip`, `python3-dev`, `build-essential`, `pkg-config`, `rsync`, `unzip`, `jq`), then clone/update repo, venv, `pip install -e`, role data dirs, and `ark deploy render` under `--generated-dir` (default: `$DATA_DIR/deploy/generated`).

**Raspberry Pi 5 / Debian 13 trixie (aarch64)** is the first observed RAG Pi target for this baseline.

On a normal sudo-capable user account, default paths `/opt/ark-pi` and `/srv/ark-pi` are prepared with sudo when needed (`mkdir` + `chown` on those leaf directories only). git clone, venv creation, `pip install -e`, and `ark deploy render` still run as the invoking user — do not pipe the whole installer through `sudo`. A real rag-pi install hit `cannot create prefix under unwritable parent: /opt` after apt prerequisites succeeded; this ownership prep fixes that case.

With `--install-services`, it copies rendered env/systemd files (backs up existing, optional `systemctl` when `--service-root` is `/`). Without that flag: OS packages (if enabled) + app bootstrap + render only.

Use `--no-os-packages` or `--package-manager none` to skip apt and only verify required commands exist. Default `--package-manager auto` uses apt when `apt-get` is available.

After a real install, validation runs automatically (app CLI, data dirs, generated templates, role-env-aware `ark preflight` / `ark llm status`, `ark deploy preflight`, optional service files). Use `--no-validate` to skip, or `--validate-only` to check an existing install without mutations. Validation does not test llama.cpp inference or network configuration.

On a real **rag-pi** install (Raspberry Pi 5 / Debian 13 trixie), `ark-rag.service` loads `/etc/ark-pi/ark-rag.env` (installed `root:root` mode `0640`), but bare `ark preflight` uses default user-local config. Load the role env before manual CLI checks (requires sudo because the env file is not world-readable):

```bash
sudo sh -c 'set -a; . /etc/ark-pi/ark-rag.env; set +a; exec /opt/ark-pi/.venv/bin/ark preflight'
sudo sh -c 'set -a; . /etc/ark-pi/ark-rag.env; set +a; exec /opt/ark-pi/.venv/bin/ark llm status'
```

With `--install-services`, installer validation prefers `/etc/ark-pi/ark-rag.env` (or `--service-root` equivalent) and uses read-only `sudo cat` when the env file is not readable unprivileged. Without `--install-services`, validation prefers `$GENERATED_DIR/ark-rag.env` (no sudo).

Does **not** install llama.cpp or models. Does **not** configure network or WiFi AP.

Plan only (includes apt package plan on Debian-family systems):

```bash
sh install.sh --role rag --dry-run
sh install.sh --role rag --no-os-packages --dry-run
sh install.sh --role rag --no-validate --dry-run
sh install.sh --role rag --install-services --dry-run
```

Validate an existing install:

```bash
sh install.sh --role rag --validate-only \
  --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data \
  --generated-dir /tmp/ark-pi-generated
```

App bootstrap:

```bash
sh install.sh --role rag --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data --yes
```

Service files into a fake root (testing/review):

```bash
sh install.sh --role rag --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data \
  --service-root /tmp/ark-pi-service-root --install-services --yes
```

Full two-Pi deployment (systemd, network) is still manual: [two-pi-manual.md](docs/deployment/two-pi-manual.md). Contract: [installer-bootstrap-contract.md](docs/deployment/installer-bootstrap-contract.md).

## Deployment artifacts

```bash
ark deploy render --output-dir /tmp/ark-pi-deploy-render --force
ark deploy preflight --generated-dir /tmp/ark-pi-deploy-render
ark deploy plan --generated-dir /tmp/ark-pi-deploy-render
ark deploy bundle --generated-dir /tmp/ark-pi-deploy-render --output /tmp/ark-pi-deploy-bundle.zip --force
ark deploy verify-bundle --bundle /tmp/ark-pi-deploy-bundle.zip
ark deploy unpack-bundle --bundle /tmp/ark-pi-deploy-bundle.zip --staging-dir /tmp/ark-pi-deploy-staging --force
```

Outputs include `ark-rag.env`, `ark-rag.service`, `ark-llm.env`, `ark-llm.service`, plus preflight/plan reports.

Warnings about missing `/opt/ark-pi` or llama.cpp on a laptop are normal. `ark preflight` checks the app using current shell env (on a Pi, load `/etc/ark-pi/ark-rag.env` via `sudo sh -c` to match the service); `ark deploy preflight` checks rendered templates.

More: [docs/deployment/README.md](docs/deployment/README.md).

## Deployment artifacts

| File | |
|------|--|
| [docs/architecture.md](docs/architecture.md) | Request flow, APIs |
| [docs/roadmap.md](docs/roadmap.md) | What's done vs TODO |
| [docs/deployment/two-pi-manual.md](docs/deployment/two-pi-manual.md) | Manual Pi setup |
| [docs/deployment/installer-bootstrap-contract.md](docs/deployment/installer-bootstrap-contract.md) | Installer contract (app bootstrap + future services) |
| [docs/deployment/README.md](docs/deployment/README.md) | Deploy doc index |
| [docs/hardware.md](docs/hardware.md) | Hardware notes |

## Not done yet

- WiFi AP
- Service install to real `/etc` via install.sh needs `--install-services` and root/sudo; llama.cpp/models/network still manual
- llama.cpp install automation
- Model download/management
- Auth
- Chroma/semantic search as default production path
- End-to-end test on real Pi hardware in this repo
- Any claim that answers are safe or medically correct

## Repo hygiene

Don't commit: `.venv/`, `.env`, `data/`, `indexes/`, `models/`, `*.gguf`, generated chunks/indexes.

## License

See [LICENSE](LICENSE).
