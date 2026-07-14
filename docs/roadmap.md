# Roadmap

Staged development plan for Ark Pi.

## What's next

The point is offline Q&A from your own index when WAN is down (e.g. *"how do I purify water?"* from docs you loaded earlier).

Working now: laptop MVP (CLI, API, web UI, workspace tools, mock LLM), deploy review commands (render through unpack), and [manual two-Pi docs](deployment/two-pi-manual.md). The deploy commands are helpers for review, not the end product.

Still TODO: OS packages, llama.cpp automation, model/corpus tooling, WiFi AP, network automation, auth, semantic/Chroma retrieval.

---

## 48. Two-Pi smoke command

`ark appliance smoke` with `--env-file`, `--json`, `--llm-base-url`, and `--timeout`. Validates the RAG Pi to LLM Pi OpenAI-compatible chat path using the `ark-pi-ok` diagnostic prompt. Explicit network validation for operators; not run automatically during installer preflight.

**Status: done**

---

## 49. Deterministic end-to-end ask smoke

`ark appliance ask-smoke` with `--env-file`, `--json`, `--keep`, and `--timeout`. Seeds an isolated tiny corpus, builds the `ark-smoke` index, verifies retrieval of the beacon phrase `copper lantern`, runs the normal ask pipeline through the configured LLM backend, validates the generated answer, and cleans up smoke artifacts by default.

**Status: done**

---

## 50. Appliance validation receipt

`ark appliance receipt` with `--env-file`, `--json`, `--output`, `--receipt-dir`, optional `--run-smoke`, `--run-ask-smoke`, `--hash-model`, and installer `--receipt-path` / `--receipt-dir` flags. Versioned offline JSON evidence for RAG and LLM appliances with allowlisted configuration, filesystem/deployment checks, read-only service state, and optional embedded Slice 48/49 smoke results.

**Status: done**

---

## 1. Scaffold and config

Project structure, pydantic-settings config layer, minimal Typer CLI (`ark version`, `ark status`, `ark config`), docs, deployment placeholders, offline smoke tests.

**Status: done**

## 2. Local document chunking

`ark ingest chunk` reads `.txt`, directories of `.txt`, or `.jsonl` sources and writes deterministic chunk records to JSONL. Offline tests cover splitting, source loading, and CLI behavior.

**Status: done**

## 3. Local index abstraction / simple retrieval

`ark index build|search|stats` with a pure-Python lexical `simple` backend. Index interface boundary in `ark_pi.rag` so Chroma can plug in later.

**Status: done**

## 4. RAG prompt assembly / dev ask

`ark ask` searches the local index, assembles a deterministic RAG prompt, and returns an honest dev/mock answer. No LLM calls yet.

**Status: done**

## 5. LLM client boundary / mock backend

Typed LLM client interface in `ark_pi.llm_client` with a deterministic mock backend (default) and an OpenAI-compatible HTTP client for future llama.cpp use. `ark ask` calls the configured backend after retrieval and prompt assembly. Network calls are opt-in only.

**Status: done**

## 6. Optional Chroma backend boundary

Index backend selection (`simple` default, `chroma` optional) with lazy-loaded Chroma storage behind the existing index abstraction. Manifest records backend identity. No semantic embedding pipeline yet.

**Status: done**

## 7. Explicit embedding model pipeline

Choose and wire an embedding model for semantic indexing. Evaluate retrieval quality offline.

## 8. Real semantic retrieval and evaluation

End-to-end semantic search, ranking evaluation, and tuning over Chroma-backed indexes.

## 9. FastAPI RAG service

Local FastAPI endpoints for health, config-safe status, index stats, search, and ask over the existing index and LLM client boundaries. Mock LLM default; Chroma opt-in. Laptop-safe and fully testable with FastAPI TestClient.

**Status: done**

## 10. llama.cpp server deployment

Deploy llama.cpp on ark-llm Pi. ark-rag uses the existing OpenAI-compatible client over Ethernet. Optional for laptop dev/tests.

## 11. Minimal web UI

Built-in single-page HTML at `GET /` and `GET /ui`. Inline JS calls `POST /api/ask`. No npm, CDN, or build chain.

**Status: done**

## 12. Web text ingest

Browser and API path to paste plain text, write chunks JSONL, and build a local index via `POST /api/ingest/text`. Reuses existing chunking and index facades. No file uploads or document parsers.

**Status: done**

## 13. Workspace index catalog

Named indexes under `workspace_dir` with local `catalog.json` metadata. `GET /api/indexes`, workspace-mode text ingest, and web UI index dropdown. No raw filesystem paths in normal use.

**Status: done**

## 14. Local file ingest

Server-side `.txt` file and directory ingest from `source_dir` (`ARK_SOURCE_DIR`) into named workspace indexes. `POST /api/ingest/path`, web UI **Add local file** panel, and `ark workspace ingest-path`. Safe path containment; no browser upload or document parsers.

**Status: done**

## 15. Browser text file import

Browser-side `.txt` import in the built-in web UI. JavaScript reads the selected file locally and sends its text to the existing `POST /api/ingest/text` endpoint. No backend multipart upload, no raw file storage, no parser dependencies.

**Status: done**

## 16. Workspace index management

Catalog-aware deletion of named workspace indexes. `DELETE /api/indexes/{slug}` and web UI **Delete selected index** with confirmation. Deletes are constrained to `ARK_WORKSPACE_DIR`; catalog entries are removed after filesystem cleanup.

**Status: done**

## 17. Workspace CLI management

Terminal parity for workspace indexes: `ark workspace list`, `show`, and `delete` (with `--yes`). Reuses catalog-aware helpers; no filesystem scanning beyond the workspace catalog.

**Status: done**

## 18. Workspace export

Local backup of workspace catalog and named indexes to a zip archive. `ark workspace export`, `POST /api/workspace/export`, and web UI **Export workspace** panel. Stdlib `zipfile` only; paths derived from workspace layout.

**Status: done**

## 19. Browser workspace export download

Download workspace export zips directly in the browser. `POST /api/workspace/export/download` returns an in-memory zip; web UI **Download export** button. Reuses existing export validation and archive-building logic. Server-side path export unchanged.

**Status: done**

## 20. Browser workspace import upload

Upload and restore workspace export zips directly from the browser. `POST /api/workspace/import/upload` accepts raw `application/zip` (no multipart); web UI **Upload and import** button. Reuses safe importer validation; size limited by `ARK_MAX_IMPORT_BYTES` (default 50 MiB). Server-side path import unchanged.

**Status: done**

## 21. LLM backend diagnostics

Passive LLM status and explicit diagnostic test across CLI (`ark llm status`, `ark llm test`), API (`GET /api/llm/status`, `POST /api/llm/test`), and web UI **LLM diagnostics** panel. Passive endpoints do not contact ark-llm; active test uses the existing LLM client boundary.

**Status: done**

## 22. Local appliance init

Explicit initialization across CLI (`ark init`), API (`POST /api/init`), and web UI **Initialize appliance storage** panel. Creates `ARK_WORKSPACE_DIR`, `ARK_SOURCE_DIR`, workspace indexes directory, optionally empty `catalog.json` and sample text source, then reports passive preflight. Does not configure networking, systemd, or models.

**Status: done**

## 23. Quickstart sample index

One-step dev/appliance smoke flow across CLI (`ark quickstart`), API (`POST /api/quickstart`), and web UI **Quickstart** panel. Initializes local storage, creates sample text source, builds a named workspace index, and verifies the RAG loop with the mock LLM. No network, Chroma, or real model required.

**Status: done**

## 24. Deployment template rendering

Dry-run rendering of ark-rag and ark-llm env/systemd templates via CLI (`ark deploy render`). Generates reviewable examples under a chosen output directory without installing units, calling systemctl, or configuring networking.

**Status: done**

## 25. Deployment preflight

Dry-run inspection of rendered ark-rag and ark-llm deployment templates via CLI (`ark deploy preflight`) and API (`GET /api/deploy/preflight`). Checks generated files, env parse, and existence of paths named in templates without installing services, calling systemctl, or performing network checks.

**Status: done**

## 26. Deployment install plan

Dry-run install planning for rendered ark-rag and ark-llm templates via CLI (`ark deploy plan`) and API (`GET /api/deploy/plan`). Composes deployment preflight with planned copy targets and manual commands without executing them or mutating host service state.

**Status: done**

## 27. Deployment bundle

Dry-run deployment bundle generation via CLI (`ark deploy bundle`). Packages rendered templates, deployment preflight JSON, install plan JSON and markdown, checksum manifest, and README into a portable zip for operator review without installing services or mutating host state.

**Status: done**

## 28. Deployment bundle verification

Read-only deployment bundle verification via CLI (`ark deploy verify-bundle`). Validates bundle zip structure, manifest schema, dry-run safety flags, role-specific contents, report JSON, plan safety, and SHA-256 checksums without extracting files or mutating host state.

**Status: done**

## 29. Deployment bundle unpack

Verified deployment bundle unpack via CLI (`ark deploy unpack-bundle`). Validates a bundle, then extracts templates and reports into a safe staging directory without writing to system paths or installing services.

**Status: done**

## 30. Two-Pi manual deployment docs

Manual two-Pi setup guide: mock-first smoke, deploy artifacts, LLM diagnostics, systemd by hand. [docs/deployment/two-pi-manual.md](deployment/two-pi-manual.md).

**Status: done**

## 31. Appliance preflight readiness

Passive operator checklist across CLI (`ark preflight`), API (`GET /api/preflight`), and web UI **Appliance preflight** panel. Checks workspace/source paths, catalog health, index roots, source ingest readiness, index backend availability, passive LLM config, import limits, and disk space without network calls or directory creation.

**Status: done**

## 47. Partner Pi address configuration

Explicit installer-time configuration for the partner LLM Pi address on ark-rag. `install.sh --llm-base-url` / `--partner-ip` renders `ARK_LLM_BASE_URL` into `ark-rag.env` so IP-based two-Pi installs do not require hand-editing `/etc/ark-pi/ark-rag.env`.

**Status: done**

## 48. Partner Pi network auto-discovery

mDNS hostname resolution, LAN scanning, and DHCP/router integration for finding ark-llm automatically. Out of scope for slice 47; operators configure static IPs, DHCP reservations, or `/etc/hosts` today.

**Status: future**

## 32. WiFi AP and systemd deployment

Production deployment on both Pis: static Ethernet, WiFi AP on ark-rag, systemd units, storage mounts. See `deploy/`.

## 33. SimpleWiki ingest

Ingest a SimpleWiki dump (or subset) as a reference corpus. Dump files stay out of git. Use `ark corpus prepare-wikipedia` (Slice 52) to normalize local pages-articles XML dumps to JSONL, then `ark corpus ingest` (Slice 51) for resumable bulk load.

**Status: done** (preparation + ingest path)

## 52. SimpleWiki dump normalization

Offline streaming MediaWiki XML normalizer: `ark corpus prepare-wikipedia`. Converts local `.xml`/`.gz`/`.bz2` pages-articles dumps to canonical JSONL with conservative wikitext cleanup, provenance manifests, checksum verification, and resumable preparation state. Dump download remains operator-controlled. Multistream random access and semantic embeddings are later work.

**Status: done**

## 51. Resumable corpus ingest

Streamed, checkpointed bulk corpus ingest for JSONL and recursive `.txt` directories into named workspace indexes. CLI: `ark corpus ingest`, `ark corpus status`. Run state under `$ARK_WORKSPACE_DIR/corpus-runs/`. Simple backend only; semantic embeddings deferred.

**Status: done**

## 34. Workspace import / restore

Restore workspace indexes from Ark Pi export archives. `ark workspace import`, `POST /api/workspace/import`, server-side path UI, and browser upload via `POST /api/workspace/import/upload`. Validates archive structure, remaps catalog paths, merges with existing catalog.

**Status: done**

## 35. Backup / export / import strategy

Export and restore indexes and config. Support rebuilding from source vs. restoring snapshots.

## 36. Installer bootstrap

`install.sh` at repo root.

**App bootstrap + deploy render + optional service install + apt OS prerequisites + install path ownership + validation (done):** RAG Pi baseline packages on Debian-family hosts, sudo prep for default `/opt/ark-pi` and `/srv/ark-pi` when needed, clone, venv, pip, data dirs, `ark deploy render`, post-install validation, and with `--install-services` env/systemd copy + systemctl when `--service-root` is `/`. First observed target: Raspberry Pi 5 / Debian 13 trixie.

```bash
sh install.sh --role rag --dry-run
sh install.sh --role rag --validate-only --prefix /path/to/prefix --data-dir /path/to/data --generated-dir /path/to/generated
sh install.sh --role rag --install-services --service-root /path/to/service-root --yes
```

**Future (not started):** WiFi/network, non-apt distros. Contract: [docs/deployment/installer-bootstrap-contract.md](deployment/installer-bootstrap-contract.md).

**Status: OS packages + path ownership + app bootstrap + render + service files + validation done; optional llama.cpp build via `--llama-build`; optional model download via `--download-model`; network not automated**

## 44. Move llama.cpp build out of app checkout + hardcoded path audit

Default llama.cpp source/build paths moved to `$DATA_DIR/vendor/llama.cpp` (`/srv/ark-pi/vendor/llama.cpp`) so optional `--llama-build` does not dirty the `/opt/ark-pi` app git checkout. Strict prefix dirty-check retained; stale `$PREFIX/vendor/` from the old default gets a clearer failure hint. Hardcoded-path audit test blocks user-specific and legacy wrong defaults in installer/runtime/docs.

**Status: done (hardware `--llama-build` rerun still pending)**

## 46. llama.cpp server bootstrap

Optional llama.cpp source build in `install.sh` for role `llm` or `both`: clone to `$DATA_DIR/vendor/llama.cpp`, cmake build `llama-server`, render `ark-llm.env` / `ark-llm.service` with `ARK_LLAMA_*` paths, validate binary and model paths. Apt extras (`cmake`, `libcurl4-openssl-dev`, `ccache`) install only with `--llama-build`. Missing GGUF is a validation warning by default; `--require-model` fails. Service install skips `systemctl start` for `ark-llm` when the model file or `llama-server` binary is absent.

```bash
sh install.sh --role llm --llama-build --dry-run
sh install.sh --role llm --llama-build --install-services --yes
sh install.sh --role llm --validate-only --install-services
```

Model acquisition, model selection benchmarking, networking/AP, and RAG-to-LLM integration smoke on real Pi hardware remain follow-up work.

**Real llm-pi baseline (before `--llama-build`):** `--role llm --install-services --no-start --yes` completed with PASS (warnings) for missing model and inactive service. Legacy `ARK_LLAMACPP_*` env keys observed on installed baseline; new renders migrate to `ARK_LLAMA_*` / `ARK_MODEL_*`.

**Real llm-pi `--llama-build` finding (hotfix + path move):** CMake must configure with an explicit llama.cpp source directory (`cmake -S $LLAMA_DIR -B $LLAMA_BUILD_DIR`). Without `-S`, CMake used the caller working directory and failed on real hardware. Default llama.cpp paths now live under `$DATA_DIR/vendor/llama.cpp` so builds do not dirty `/opt/ark-pi`. Real-hardware llama.cpp build success is pending Audrey’s post-merge rerun.

## 47. Model download bootstrap

Optional GGUF model acquisition in `install.sh` for role `llm` or `both` with `--download-model` (not default). Default preset `qwen3-4b-q4km` (Qwen3 4B Q4_K_M, ~2.5 GB, Apache-2.0, SHA256-pinned). Advanced preset `qwen3-8b-q4km` (Qwen3 8B Q4_K_M, ~5 GB, Apache-2.0). Custom preset requires `--model-url` or `--model-repo` + `--model-file`, plus `--model-sha256`.

```bash
sh install.sh --role llm --download-model --dry-run
sh install.sh --role llm --download-model --install-services --no-start --yes
sh install.sh --role llm --validate-only --install-services --require-model
```

Downloads use `curl`, verify SHA256 with `sha256sum`, and install atomically to `$DATA_DIR/models/model.gguf`. Skip when existing file matches checksum; fail on mismatch unless `--force-model-download`. `--dry-run` and `--validate-only` never download. **`--role rag --download-model` is rejected.**

Manual fallback remains: copy any compatible GGUF to `/srv/ark-pi/models/model.gguf`.

**Status: done (real llm-pi download smoke pending Audrey post-merge)**

Future: RAG-to-LLM end-to-end prompt smoke, networking/AP mode, model benchmarking.

## 45. Service env validation permissions

Fix env-aware validation for installed service env files (`/etc/ark-pi/*.env`, `root:root` mode `0640`). Unreadable env files fail with `role_env_read` before `ark` commands run. Real `/etc` installs use read-only `sudo cat` for validation; generated and redirected service-root env reads stay unprivileged. Printed manual validation commands use `sudo sh -c` for installed service env files.

**Status: done**

## 44. Install path ownership

Prepare default `/opt/ark-pi` and `/srv/ark-pi` with sudo when needed: `mkdir -p` on the selected leaf directories, `chown` only those paths to the invoking user, then run git/venv/pip/render/validation unprivileged. Motivated by a real rag-pi failure after apt prerequisites (`cannot create prefix under unwritable parent: /opt`). Dry-run prints the ownership plan without mutations. Rejects unsafe exact paths (`/`, `/opt`, `/srv`, etc.).

**Status: done**

## 43. Install validation

Post-install validation and `--validate-only` mode: check app CLI, role data dirs, generated templates, role-env-aware `ark preflight` / `ark llm status`, `ark deploy preflight`, optional service files, and read-only systemctl state. Flags: `--validate-only`, `--no-validate`. Does not test model inference or networking.

**Status: done**

## 44. Installer env-aware validation

Installer validation and printed post-install commands load the generated or installed role env file (`$GENERATED_DIR/ark-rag.env` or `/etc/ark-pi/ark-rag.env`) before `ark preflight` and `ark llm status`, matching the systemd service on real rag-pi installs. Safe env parsing uses an allowlist; unknown keys warn and are ignored. Observed on Raspberry Pi 5 / Debian 13 trixie: bare `ark preflight` used user-local defaults while `ark-rag.service` correctly used `/etc/ark-pi/ark-rag.env`.

**Status: done**

## 42. Install OS prerequisites

Apt-based OS package install on Debian-family systems: `ca-certificates`, `curl`, `git`, `python3`, `python3-venv`, `python3-pip`, `python3-dev`, `build-essential`, `pkg-config`, `rsync`, `unzip`, `jq`. First observed RAG Pi target: Raspberry Pi 5 / Debian 13 trixie. Flags: `--no-os-packages`, `--package-manager auto|apt|none`. Dry-run prints apt plan without calling apt or sudo.

**Status: done**

## 41. Install service files

Optional `--install-services` and `--service-root` for env/systemd install with backup, chmod, and systemctl when installing to `/`.

**Status: done**

## 40. Install deployment render

Extend `install.sh` to run installed `ark deploy render` after app bootstrap. `--generated-dir` flag, role mapping (`both` -> `all`), safe path validation.

**Status: done**

## 39. Install app bootstrap

Extend `install.sh` from planner-only to minimal app bootstrap with confirmation/`--yes`, offline-safe tests.

**Status: done**

## 38. Install bootstrap planner (v0)

Root-level planner-only `install.sh` and shell tests. Supports `--role`, `--dry-run`, future-compat flags, interactive role prompt, non-interactive failure without `--role`.

**Status: done**

## 37. Installer bootstrap contract (docs)

Document the future `install.sh` UX, flags, dry-run rules, role behavior, and safety boundaries before writing the script. See [docs/deployment/installer-bootstrap-contract.md](deployment/installer-bootstrap-contract.md).

**Status: done**

---

## Future idea: dev lab (not planned yet)

Two containerized nodes (ark-rag + ark-llm) for laptop integration testing. ark-llm could start as a mock OpenAI-compatible endpoint. Real llama.cpp inference waits until stage 8.
