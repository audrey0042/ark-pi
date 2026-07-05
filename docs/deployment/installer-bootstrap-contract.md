# Installer bootstrap contract

Design doc for `install.sh`. **Current script:** apt-based OS prerequisite install (Debian-family), app bootstrap, deploy template render, optional service file install (`--install-services`), and post-install / validation-only checks. llama.cpp, model download, and network/WiFi remain manual.

Manual deployment is the current complete path: [two-pi-manual.md](two-pi-manual.md).

## Status

- `install.sh` at repo root. On apt-based systems, installs the RAG Pi OS prerequisite baseline before app bootstrap.
- App bootstrap + `ark deploy render` into `--generated-dir`.
- `--install-services` copies rendered env/systemd files under `--service-root` (default `/`). Backs up existing files. `systemctl daemon-reload/enable/start` when service root is `/` (respects `--no-enable`, `--no-start`).
- `--service-root /tmp/...` for safe testing: files only, no systemctl.
- `--no-os-packages` / `--package-manager none` skip apt and verify commands only. `--package-manager auto` (default) uses apt when `apt-get` exists.
- `--dry-run` prints the plan (including apt commands when enabled) with no mutations. Non-interactive install requires `--yes`.
- Post-install validation runs after a successful real install unless `--no-validate`. `--validate-only` checks an existing install with no mutations.
- Not implemented: llama.cpp, model fetch, WiFi/network, auth, non-apt package managers.
- [two-pi-manual.md](two-pi-manual.md) stays the full deployment guide.

```bash
sh install.sh --role rag --dry-run
sh install.sh --role rag --no-os-packages --dry-run
sh install.sh --role rag --install-services --dry-run
sh install.sh --role rag --service-root /tmp/ark-pi-service-root --install-services --yes
sh install.sh --role rag --validate-only --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data --generated-dir /tmp/ark-pi-generated
```

## OS prerequisites (apt)

On Debian-family hosts, `install.sh` installs this apt package baseline before app bootstrap:

`ca-certificates`, `curl`, `git`, `python3`, `python3-venv`, `python3-pip`, `python3-dev`, `build-essential`, `pkg-config`, `rsync`, `unzip`, `jq`

This baseline was derived from a real rag-pi inventory: **Raspberry Pi 5 / Debian 13 trixie (aarch64)**, Python 3.13.5. On that host, `git` and `python3-pip` were missing; `python3-venv` was present. `python3-dev`, `build-essential`, and `pkg-config` provide ARM64/Python build insurance; `rsync`, `unzip`, and `jq` are practical operator tools.

**Out of scope:** llama.cpp build dependencies, model download, WiFi AP, and network automation.

Flags: `--no-os-packages` and `--package-manager none` skip apt and verify `git`, `python3`, `curl`, and `python3 -m venv` only. `--package-manager auto` (default) uses apt when `apt-get` exists.

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
| `--no-os-packages` | Skip apt install; verify `git`, `python3`, `curl`, and `python3 -m venv` only |
| `--package-manager auto\|apt\|none` | Package manager mode (default: `auto`; `none` = skip OS packages) |
| `--validate-only` | Validate an existing install; no host mutations |
| `--no-validate` | Skip automatic post-install validation |
| `--help` | Usage and exit |

Defaults should be boring and printed in the summary. All flags must work when passed as `sh -s -- FLAG ...` after a curl pipe.

## Interactive prompts

- Ask for role when `--role` is omitted.
- Ask before any file write, package install, or `sudo` command.
- Ask before `systemctl enable` or `systemctl start` unless `--yes`.
- In `--dry-run`, show what would happen; do not prompt for confirmation to proceed (there is nothing to proceed with).

## Dry-run behavior

- Must not mutate the host (no packages, clones, copies, systemd, network, no `ark deploy render`).
- Print planned actions: apt package install (when enabled), clone/update, venv, `pip install`, `ark deploy render`, data dirs. Future: env/service copies, enable/start.
- Print detected OS, architecture, role, package manager, `--prefix`, `--data-dir`, `--generated-dir`, branch, repo.
- Exit nonzero if the role or platform is unsupported.
- Do not run validation commands in `--dry-run`; print that validation would run (or print validation plan for `--validate-only`).

## Validation

Validation is read-only. It does not install llama.cpp, download models, configure networking, or start/enable services.

### Modes

- **Post-install (default):** after a successful real install, run validation unless `--no-validate`.
- **`--validate-only`:** skip all install steps; check an existing install using `--role`, `--prefix`, `--data-dir`, `--generated-dir`, and `--service-root`.
- **`--dry-run` + `--validate-only`:** print validation plan only.

### Checks

Each check prints `[pass]`, `[warning]`, or `[fail]` with an id and message.

Common: prefix exists, `$PREFIX/.venv/bin/ark` executable, `ark --help`, data dir, generated dir, role deployment templates, `ark deploy preflight`.

Role-specific:

- **rag:** workspace/sources dirs; `ark llm status` (warning if LLM offline).
- **llm:** model dir (required); GGUF file under models (warning only).

Services (when `--install-services`, or service files exist under service root): env files under `$SERVICE_ROOT/etc/ark-pi`, unit files under `$SERVICE_ROOT/etc/systemd/system`. When service root is `/`, read-only `systemctl is-enabled` / `is-active` (warnings only).

### Exit codes

- **0:** all checks pass, or only warnings.
- **Nonzero:** one or more hard failures.

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
3. Resolve package manager (`auto` / `apt` / `none`).
4. Prompt for role if needed.
5. Build install plan (role-specific steps + OS packages when enabled).
6. Print summary.
7. Exit if `--dry-run`.
8. Ask confirmation unless `--yes`.
9. Install OS prerequisite packages via apt (when enabled; uses sudo when not root).
10. Clone or update repo at `--prefix`.
11. Create Python virtualenv and `pip install` Ark Pi.
12. Run `ark deploy render --output-dir $GENERATED_DIR --role rag|llm|all --force` (implemented).
13. With `--install-services`: copy env/systemd files to `$SERVICE_ROOT/etc/...`, backup existing, chmod, optional systemctl (implemented when service root is `/`).
14. llama.cpp / model fetch / network (future).
15. Run post-install validation unless `--no-validate`.
16. Print validation commands.

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
- [roadmap §36](../roadmap.md#36-installer-bootstrap): app bootstrap + OS packages + render + service files + validation done; llm/network future
