#!/bin/sh
#
# Ark Pi install bootstrap (v1).
# App bootstrap only: clone/update repo, venv, pip install, data dirs.
# Does not install OS packages, systemd units, llama.cpp, or models.
#

set -u

ROLE=""
DRY_RUN=0
YES=0
BRANCH="main"
REPO="https://github.com/audrey0042/ark-pi.git"
PREFIX="/opt/ark-pi"
DATA_DIR="/srv/ark-pi"
NO_ENABLE=0
NO_START=0

OS=""
ARCH=""

usage() {
  cat <<'EOF'
Ark Pi install bootstrap

Bootstraps the Ark Pi app: clone/update repo, Python venv, pip install -e,
and role-specific data directories under --prefix and --data-dir.

Does not install OS packages, write /etc files, install systemd units,
run sudo/systemctl, install llama.cpp, or download models.

Usage:
  sh install.sh [options]

Options:
  --role rag|llm|both    Install role (required in non-interactive mode)
  --dry-run              Print plan only; no host changes
  --yes                  Skip confirmation (required for non-interactive install)
  --branch BRANCH        Git branch (default: main)
  --repo URL             Git repository URL
  --prefix PATH          Install prefix (default: /opt/ark-pi)
  --data-dir PATH        Data root (default: /srv/ark-pi)
  --no-enable            Reserved: skip systemctl enable (service slice, not implemented)
  --no-start             Reserved: skip systemctl start (service slice, not implemented)
  --help                 Show this help

Examples:
  sh install.sh --role rag --dry-run
  sh install.sh --role rag --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data --yes
  curl -fsSL https://raw.githubusercontent.com/audrey0042/ark-pi/main/install.sh | sh -s -- --role rag --dry-run
EOF
}

die() {
  echo "install.sh: $*" >&2
  exit 1
}

is_interactive() {
  [ -t 0 ]
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --help)
        usage
        exit 0
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --yes)
        YES=1
        shift
        ;;
      --no-enable)
        NO_ENABLE=1
        shift
        ;;
      --no-start)
        NO_START=1
        shift
        ;;
      --role=*)
        ROLE="${1#*=}"
        shift
        ;;
      --role)
        if [ $# -lt 2 ]; then
          die "missing value for --role"
        fi
        ROLE="$2"
        shift 2
        ;;
      --branch=*)
        BRANCH="${1#*=}"
        shift
        ;;
      --branch)
        if [ $# -lt 2 ]; then
          die "missing value for --branch"
        fi
        BRANCH="$2"
        shift 2
        ;;
      --repo=*)
        REPO="${1#*=}"
        shift
        ;;
      --repo)
        if [ $# -lt 2 ]; then
          die "missing value for --repo"
        fi
        REPO="$2"
        shift 2
        ;;
      --prefix=*)
        PREFIX="${1#*=}"
        shift
        ;;
      --prefix)
        if [ $# -lt 2 ]; then
          die "missing value for --prefix"
        fi
        PREFIX="$2"
        shift 2
        ;;
      --data-dir=*)
        DATA_DIR="${1#*=}"
        shift
        ;;
      --data-dir)
        if [ $# -lt 2 ]; then
          die "missing value for --data-dir"
        fi
        DATA_DIR="$2"
        shift 2
        ;;
      --)
        shift
        if [ $# -gt 0 ]; then
          die "unexpected positional arguments: $*"
        fi
        ;;
      -*)
        die "unknown flag: $1"
        ;;
      *)
        die "unexpected argument: $1"
        ;;
    esac
  done
}

normalize_role_choice() {
  _choice="$1"
  while [ -n "$_choice" ] && [ "${_choice#?}" != "$_choice" ]; do
    case $_choice in
      " "*|"\t"*) _choice="${_choice#?}" ;;
      *) break ;;
    esac
  done
  while [ -n "$_choice" ]; do
    case $_choice in
      *" "|*"\t") _choice="${_choice%?}" ;;
      *) break ;;
    esac
  done
  case "$_choice" in
    1|rag) echo rag ;;
    2|llm) echo llm ;;
    3|both) echo both ;;
    *) echo "$_choice" ;;
  esac
}

prompt_role() {
  _attempts=0
  echo "Choose Ark Pi role:"
  echo "1) rag  - Web UI, API, ingest, index, RAG client"
  echo "2) llm  - OpenAI-compatible local model server"
  echo "3) both - Single-host development/test"
  while [ "$_attempts" -lt 3 ]; do
    printf "Role [rag/llm/both]: "
    if ! read -r _choice; then
      die "--role is required in non-interactive mode (use --role rag|llm|both)"
    fi
    _normalized=$(normalize_role_choice "$_choice")
    case "$_normalized" in
      rag|llm|both)
        ROLE="$_normalized"
        return 0
        ;;
      *)
        _attempts=$((_attempts + 1))
        echo "install.sh: invalid role; choose rag, llm, both, or 1/2/3" >&2
        ;;
    esac
  done
  die "too many invalid role attempts"
}

validate_role() {
  case "$ROLE" in
    rag|llm|both) ;;
    *) die "unsupported role: $ROLE (expected rag, llm, or both)" ;;
  esac
}

detect_platform() {
  OS=$(uname -s 2>/dev/null || echo unknown)
  ARCH=$(uname -m 2>/dev/null || echo unknown)
  if [ "$OS" != "Linux" ]; then
    die "unsupported OS: $OS (Linux required)"
  fi
  case "$ARCH" in
    x86_64|aarch64|arm64|armv7l) ;;
    *)
      echo "install.sh: warning: unrecognized architecture: $ARCH" >&2
      ;;
  esac
}

print_common_summary() {
  echo "Ark Pi install bootstrap"
  echo ""
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run: no host changes will be made."
  else
    echo "App bootstrap: writes only under --prefix and --data-dir."
  fi
  echo ""
  echo "Detected OS:           $OS"
  echo "Detected architecture: $ARCH"
  echo "Role:                  $ROLE"
  echo "Repo:                  $REPO"
  echo "Branch:                $BRANCH"
  echo "Prefix:                $PREFIX"
  echo "Data dir:              $DATA_DIR"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run:               yes"
  else
    echo "Dry run:               no"
  fi
  if [ "$YES" -eq 1 ]; then
    echo "Yes:                   yes"
  else
    echo "Yes:                   no"
  fi
  if [ "$NO_ENABLE" -eq 1 ]; then
    echo "Enable services:       no (--no-enable, reserved for future service slice)"
  else
    echo "Enable services:       reserved for future service slice"
  fi
  if [ "$NO_START" -eq 1 ]; then
    echo "Start services:        no (--no-start, reserved for future service slice)"
  else
    echo "Start services:        reserved for future service slice"
  fi
  echo ""
}

data_dirs_for_role() {
  case "$ROLE" in
    rag)
      echo "$DATA_DIR/data/workspace"
      echo "$DATA_DIR/data/sources"
      ;;
    llm)
      echo "$DATA_DIR/models"
      ;;
    both)
      echo "$DATA_DIR/data/workspace"
      echo "$DATA_DIR/data/sources"
      echo "$DATA_DIR/models"
      ;;
  esac
}

print_app_bootstrap_steps() {
  echo "App bootstrap steps:"
  echo "  1. Clone or update Ark Pi at $PREFIX from $REPO (branch $BRANCH)."
  echo "  2. Create Python virtualenv at $PREFIX/.venv."
  echo "  3. Run $PREFIX/.venv/bin/pip install -e $PREFIX"
  echo "  4. Create role-specific data directories:"
  for _dir in $(data_dirs_for_role); do
    echo "       $_dir"
  done
  echo "  5. Verify $PREFIX/.venv/bin/ark --help"
}

print_future_service_steps() {
  echo ""
  echo "Future steps (not implemented in this slice):"
  echo "  - Install OS packages (apt/dnf/etc.)"
  echo "  - Render and install env/systemd files under /etc"
  echo "  - systemctl enable/start services"
  echo "  - Install llama.cpp or download GGUF models"
  echo "  - Configure WiFi AP or network"
}

print_dry_run_footer() {
  echo ""
  echo "No changes were made."
  echo "Service install remains manual: docs/deployment/two-pi-manual.md"
}

print_plan() {
  print_common_summary
  print_app_bootstrap_steps
  print_future_service_steps
  print_dry_run_footer
}

check_dependencies() {
  if ! command_exists git; then
    die "git not found. Install git manually; this installer does not install OS packages yet."
  fi
  if ! command_exists python3; then
    die "python3 not found. Install Python 3.12+ manually; this installer does not install OS packages yet."
  fi
  if ! python3 -m venv --help >/dev/null 2>&1; then
    die "python3 -m venv is not available. Install python3-venv manually."
  fi
}

check_path_writable() {
  _path="$1"
  _label="$2"
  if [ -e "$_path" ]; then
    if [ ! -w "$_path" ]; then
      die "$_label is not writable: $_path"
    fi
    return 0
  fi
  _parent=$(dirname "$_path")
  while [ ! -e "$_parent" ]; do
    _parent=$(dirname "$_parent")
  done
  if [ ! -w "$_parent" ]; then
    die "cannot create $_label under unwritable parent: $_parent"
  fi
}

prefix_is_empty() {
  if [ ! -d "$PREFIX" ]; then
    return 0
  fi
  if [ -z "$(ls -A "$PREFIX" 2>/dev/null)" ]; then
    return 0
  fi
  return 1
}

ensure_clean_prefix() {
  if [ -e "$PREFIX" ] && [ ! -d "$PREFIX" ]; then
    die "prefix exists but is not a directory: $PREFIX"
  fi
  if [ ! -e "$PREFIX" ]; then
    return 0
  fi
  if [ -d "$PREFIX/.git" ]; then
    if [ -n "$(git -C "$PREFIX" status --porcelain 2>/dev/null)" ]; then
      die "prefix git checkout has local changes; commit or stash before re-running install.sh"
    fi
    return 0
  fi
  if prefix_is_empty; then
    return 0
  fi
  die "prefix exists, is not empty, and is not a git checkout: $PREFIX"
}

require_confirmation_for_mutation() {
  if [ "$YES" -eq 1 ]; then
    return 0
  fi
  if ! is_interactive; then
    die "refusing to modify host in non-interactive mode without --yes (use --yes or --dry-run)"
  fi
  echo "This will bootstrap the Ark Pi app:"
  echo "  Prefix:   $PREFIX"
  echo "  Data dir: $DATA_DIR"
  echo "  Role:     $ROLE"
  echo ""
  printf "Proceed? [y/N]: "
  if ! read -r _answer; then
    echo "Aborted. No changes made."
    exit 0
  fi
  case "$_answer" in
    y|Y|yes|Yes|YES) ;;
    *)
      echo "Aborted. No changes made."
      exit 0
      ;;
  esac
}

clone_or_update_repo() {
  if [ ! -d "$PREFIX" ]; then
    _parent=$(dirname "$PREFIX")
    mkdir -p "$_parent"
    git clone --branch "$BRANCH" "$REPO" "$PREFIX"
    return 0
  fi
  if [ -d "$PREFIX/.git" ]; then
    git -C "$PREFIX" fetch origin "$BRANCH"
    git -C "$PREFIX" checkout "$BRANCH"
    return 0
  fi
  git clone --branch "$BRANCH" "$REPO" "$PREFIX"
}

create_venv_and_install() {
  _venv="$PREFIX/.venv"
  if [ ! -d "$_venv" ]; then
    python3 -m venv "$_venv"
  fi
  "$_venv/bin/pip" install -e "$PREFIX"
  "$_venv/bin/ark" --help >/dev/null
}

create_data_dirs() {
  for _dir in $(data_dirs_for_role); do
    mkdir -p "$_dir"
  done
}

print_validation_commands() {
  echo ""
  echo "Validation commands:"
  echo "  $PREFIX/.venv/bin/ark preflight"
  echo "  $PREFIX/.venv/bin/ark llm status"
  echo "  $PREFIX/.venv/bin/ark llm test --llm-backend mock"
  echo "  curl http://127.0.0.1:8000/healthz"
  echo "  curl http://127.0.0.1:8000/api/status"
  echo ""
  echo "Service install (systemd, /etc) is not implemented."
  echo "For full deployment, see docs/deployment/two-pi-manual.md"
}

print_success_message() {
  echo ""
  echo "App bootstrap complete."
  echo "Prefix:   $PREFIX"
  echo "Data dir: $DATA_DIR"
  echo "Role:     $ROLE"
  echo "Created data directories:"
  for _dir in $(data_dirs_for_role); do
    echo "  $_dir"
  done
  print_validation_commands
}

run_bootstrap() {
  check_dependencies
  check_path_writable "$PREFIX" "prefix"
  check_path_writable "$DATA_DIR" "data dir"
  ensure_clean_prefix
  clone_or_update_repo
  create_venv_and_install
  create_data_dirs
  print_success_message
}

main() {
  parse_args "$@"
  detect_platform
  if [ -z "$ROLE" ]; then
    if is_interactive; then
      prompt_role
    else
      die "--role is required in non-interactive mode (use --role rag|llm|both)"
    fi
  fi
  validate_role

  if [ "$DRY_RUN" -eq 1 ]; then
    print_plan
    exit 0
  fi

  print_common_summary
  print_app_bootstrap_steps
  print_future_service_steps
  echo ""
  require_confirmation_for_mutation
  run_bootstrap
}

main "$@"
