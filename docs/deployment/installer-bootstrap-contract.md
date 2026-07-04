# Installer bootstrap contract

Design doc for `install.sh`. **Current script:** app bootstrap, deploy template render, and optional service file install (`--install-services`). OS packages, llama.cpp, model download, and network/WiFi remain manual.

Manual deployment is the current complete path: [two-pi-manual.md](two-pi-manual.md).

## Status

- `install.sh` at repo root. App bootstrap + `ark deploy render` into `--generated-dir`.
- `--install-services` copies rendered env/systemd files under `--service-root` (default `/`). Backs up existing files. `systemctl daemon-reload/enable/start` when service root is `/` (respects `--no-enable`, `--no-start`).
- `--service-root /tmp/...` for safe testing: files only, no systemctl.
- `--dry-run` prints the plan with no mutations. Non-interactive install requires `--yes`.
- Not implemented: OS package install, llama.cpp, model fetch, WiFi/network, auth.
- [two-pi-manual.md](two-pi-manual.md) stays the full deployment guide.

```bash
sh install.sh --role rag --dry-run
sh install.sh --role rag --install-services --dry-run
sh install.sh --role rag --service-root /tmp/ark-pi-service-root --install-services --yes
```

## Target user experience

Interactive one-liner (planner v0; pass `--role` when piping from curl):

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role rag --dry-run
```

Full installer flow (future, after planner):

1. Script starts (stdin from curl pipe is fine).
2. If `--role` is missing, prompt: `rag`, `llm`, or `both`.
3. Build an install plan from flags + detected OS/arch.
4. Print a summary of every change (packages, dirs, copies, systemd).
5. Ask for confirmation before any host mutation, unless `--yes`.
6. Run the plan, then print validation commands.

Non-interactive examples (also planned):

```bash
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role rag
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role llm
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role both --dry-run
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role llm --yes
curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role both --branch main
```

Flags after the script name use `sh -s --` when piping from curl.

## Roles

| Role | Purpose | Expected host changes |
|------|---------|----------------------|
| `rag` | Web UI, API, ingest, workspace, index, RAG client | Python venv, repo checkout, workspace/source dirs, `ark-rag.env`, `ark-rag.service` |
| `llm` | OpenAI-compatible local server (usually llama.cpp) | Model dir, llama.cpp/server prerequisites, `ark-llm.env`, `ark-llm.service` |
| `both` | Single-host dev or smoke test | All of the above on one machine |

## Flags

| Flag | Meaning |
|------|---------|
| `--role rag\|llm\|both` | Which install path to run |
| `--dry-run` | Print plan only; no host changes |
| `--yes` | Skip confirmation prompts |
| `--branch main` | Git branch to clone/checkout |
| `--repo https://github.com/audrey0042/ark-pi.git` | Source repo URL |
| `--prefix /opt/ark-pi` | Install root for checkout and venv |
| `--data-dir /srv/ark-pi` | Runtime data root (workspace, sources, models) |
| `--generated-dir PATH` | Render deployment templates here (default: `$DATA_DIR/deploy/generated`) |
| `--install-services` | Install rendered env/systemd files after render |
| `--service-root PATH` | Root for service paths (default `/`; use `/tmp/...` for testing) |
| `--no-enable` | Skip `systemctl enable` when installing to `/` |
| `--no-start` | Skip `systemctl start` when installing to `/` |
| `--help` | Usage and exit |

Defaults should be boring and printed in the summary. All flags must work when passed as `sh -s -- FLAG ...` after a curl pipe.

## Interactive prompts

- Ask for role when `--role` is omitted.
- Ask before any file write, package install, or `sudo` command.
- Ask before `systemctl enable` or `systemctl start` unless `--yes`.
- In `--dry-run`, show what would happen; do not prompt for confirmation to proceed (there is nothing to proceed with).

## Dry-run behavior

- Must not mutate the host (no packages, clones, copies, systemd, network, no `ark deploy render`).
- Print planned actions: clone/update, venv, `pip install`, `ark deploy render`, data dirs. Future: env/service copies, enable/start.
- Print detected OS, architecture, role, `--prefix`, `--data-dir`, `--generated-dir`, branch, repo.
- Exit nonzero if the role or platform is unsupported.

## Safety rules

- Fail fast if not Linux or if the OS/distro is unsupported.
- Always show the full plan before the first mutation.
- Every `sudo` command is visible in the plan and in stdout.
- Never download a GGUF model without explicit user action.
- Never overwrite existing env or unit files without backup or confirmation.
- Never enable or start services without confirmation unless `--yes`.
- Reruns should be idempotent where practical (skip existing venv, warn on existing units).
- End with a short list of validation commands the operator can run.

## Expected implementation outline

1. Parse flags.
2. Detect OS and architecture.
3. Prompt for role if needed.
4. Build install plan (role-specific steps).
5. Print summary.
6. Exit if `--dry-run`.
7. Ask confirmation unless `--yes`.
8. Clone or update repo at `--prefix`.
9. Create Python virtualenv and `pip install` Ark Pi.
11. Run `ark deploy render --output-dir $GENERATED_DIR --role rag|llm|all --force` (implemented).
12. With `--install-services`: copy env/systemd files to `$SERVICE_ROOT/etc/...`, backup existing, chmod, optional systemctl (implemented when service root is `/`).
13. OS package install (future).
14. llama.cpp / model fetch / network (future).
15. Print validation commands.

## Role-specific install notes

### `rag`

- Install Python and project dependencies.
- Create workspace and source directories under `--data-dir`.
- Default `ARK_LLM_BACKEND=mock` unless an LLM base URL is supplied.
- Render `ark-rag.env` and `ark-rag.service` into `--generated-dir` (review only; not copied to `/etc`).
- Print: `ark preflight`, `ark llm status`.

### `llm`

- Prepare model directory under `--data-dir`; do not fetch a GGUF silently.
- llama.cpp build/install may live in this script or a separate helper (open decision).
- Render `ark-llm.env` and `ark-llm.service` into `--generated-dir` (review only).
- Print commands to verify the llama.cpp server responds (exact endpoint depends on build).

### `both`

- For single-host dev/smoke tests.
- Default `ARK_LLM_BASE_URL` to a local address (e.g. `http://127.0.0.1:8080`).
- Run rag and llm steps in a sensible order (llm paths before rag points at them).

## Validation commands to print

After install, the script should suggest:

```bash
ark preflight
ark llm status
ark llm test --llm-backend mock
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/status
```

For `llm` or `both` with a real backend configured, also suggest `ark llm test --llm-backend openai-compatible --llm-base-url <url>` once the server is up.

## What the first installer should avoid

- WiFi AP setup
- Firewall rules
- Automatic model download
- Automatic Chroma/embedding setup
- Authentication
- Hardware-specific tuning
- Extra background services beyond the selected role unit(s)

## Open decisions

- Which Linux distros to support first (Debian/Raspberry Pi OS vs others).
- Whether llama.cpp build belongs in `install.sh` or a separate `llm` helper script.
- Dedicated service user vs install-as-current-user.
- Backup strategy for existing `/etc/ark-pi/*.env` and systemd units.
- Version pinning and checksum verification for the installer script itself.
- Whether to ship `uninstall.sh` or document manual teardown only.

## Related docs

- [two-pi-manual.md](two-pi-manual.md): current manual path
- [README deployment artifacts](../../README.md#deployment-artifacts): `ark deploy *` review commands
- [roadmap §36](../roadmap.md#36-installer-bootstrap): app bootstrap done; service install future
