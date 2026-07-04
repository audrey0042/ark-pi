#!/bin/sh
#
# Ark Pi install bootstrap (v4).
# App bootstrap, deploy render, optional service install, apt OS prerequisites.
# Does not install llama.cpp or models.
#

set -u

ROLE=""
DRY_RUN=0
YES=0
BRANCH="main"
REPO="https://github.com/audrey0042/ark-pi.git"
PREFIX="/opt/ark-pi"
DATA_DIR="/srv/ark-pi"
GENERATED_DIR=""
SERVICE_ROOT="/"
INSTALL_SERVICES=0
NO_ENABLE=0
NO_START=0
NO_OS_PACKAGES=0
PACKAGE_MANAGER="auto"
PKG_INSTALL_ENABLED=0
RESOLVED_PKG_MGR="none"

OS=""
ARCH=""

APT_PACKAGES="ca-certificates curl git python3 python3-venv python3-pip"

usage() {
  cat <<'EOF'
Ark Pi install bootstrap

Bootstraps the Ark Pi app: clone/update repo, Python venv, pip install -e,
role-specific data directories, deployment template render, and optional
env/systemd file install.

Does not install llama.cpp or download models. On Debian-family hosts,
can install minimal apt prerequisites (git, python3, python3-venv, etc.).

Usage:
  sh install.sh [options]

Options:
  --role rag|llm|both       Install role (required in non-interactive mode)
  --dry-run                 Print plan only; no host changes
  --yes                     Skip confirmation (required for non-interactive install)
  --branch BRANCH           Git branch (default: main)
  --repo URL                Git repository URL
  --prefix PATH             Install prefix (default: /opt/ark-pi)
  --data-dir PATH           Data root (default: /srv/ark-pi)
  --generated-dir PATH      Render templates here (default: $DATA_DIR/deploy/generated)
  --install-services        Install rendered env/systemd files (explicit opt-in)
  --service-root PATH       Root for service files (default: /)
  --no-os-packages          Skip apt package install; check commands only
  --package-manager MODE    auto, apt, or none (default: auto)
  --no-enable               Skip systemctl enable (when installing to /)
  --no-start                Skip systemctl start (when installing to /)
  --help                    Show this help

Examples:
  sh install.sh --role rag --dry-run
  sh install.sh --role rag --no-os-packages --dry-run
  sh install.sh --role rag --install-services --dry-run
  sh install.sh --role rag --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data --service-root /tmp/ark-pi-service-root --install-services --yes
EOF
}

die() {
  echo "install.sh: $*" >&2
  exit 1
}

is_interactive() {
  [ -t 0 ]
}

is_root() {
  [ "$(effective_uid)" -eq 0 ]
}

effective_uid() {
  if [ -n "${ARK_PI_INSTALL_TEST_EUID:-}" ]; then
    echo "$ARK_PI_INSTALL_TEST_EUID"
    return 0
  fi
  id -u
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_as_root() {
  if is_root; then
    "$@"
    return $?
  fi
  if [ "${ARK_PI_INSTALL_TEST_NO_SUDO:-0}" = "1" ]; then
    die "root or sudo required for: $*"
  fi
  if command_exists sudo; then
    sudo "$@"
    return $?
  fi
  die "root or sudo required for: $*"
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
      --install-services)
        INSTALL_SERVICES=1
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
      --no-os-packages)
        NO_OS_PACKAGES=1
        shift
        ;;
      --package-manager=*)
        PACKAGE_MANAGER="${1#*=}"
        shift
        ;;
      --package-manager)
        if [ $# -lt 2 ]; then
          die "missing value for --package-manager"
        fi
        PACKAGE_MANAGER="$2"
        shift 2
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
      --generated-dir=*)
        GENERATED_DIR="${1#*=}"
        shift
        ;;
      --generated-dir)
        if [ $# -lt 2 ]; then
          die "missing value for --generated-dir"
        fi
        GENERATED_DIR="$2"
        shift 2
        ;;
      --service-root=*)
        SERVICE_ROOT="${1#*=}"
        shift
        ;;
      --service-root)
        if [ $# -lt 2 ]; then
          die "missing value for --service-root"
        fi
        SERVICE_ROOT="$2"
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

set_generated_dir_default() {
  if [ -z "$GENERATED_DIR" ]; then
    GENERATED_DIR="$DATA_DIR/deploy/generated"
  fi
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

deploy_role_for_install_role() {
  case "$ROLE" in
    rag) echo rag ;;
    llm) echo llm ;;
    both) echo all ;;
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

resolve_path_best_effort() {
  _path="$1"
  if [ -e "$_path" ]; then
    if [ -d "$_path" ]; then
      cd "$_path" && pwd -P
      return 0
    fi
    die "path is not a directory: $_path"
  fi
  _parent=$(dirname "$_path")
  _base=$(basename "$_path")
  if [ -e "$_parent" ]; then
    _resolved_parent=$(cd "$_parent" && pwd -P)
    echo "$_resolved_parent/$_base"
    return 0
  fi
  echo "$_path"
}

path_is_under() {
  _child="$1"
  _parent="$2"
  case "$_child" in
    "$_parent"|"$_parent"/*) return 0 ;;
    *) return 1 ;;
  esac
}

validate_generated_dir() {
  if [ -z "$GENERATED_DIR" ]; then
    die "generated dir must not be empty"
  fi

  _gen=$(resolve_path_best_effort "$GENERATED_DIR")
  _prefix=$(resolve_path_best_effort "$PREFIX")
  _data=$(resolve_path_best_effort "$DATA_DIR")

  case "$_gen" in
    /|/etc|/etc/*|/usr|/usr/*|/lib|/lib/*)
      die "refusing unsafe generated dir: $_gen"
      ;;
  esac

  if path_is_under "$_gen" "$_prefix"; then
    return 0
  fi
  if path_is_under "$_gen" "$_data"; then
    return 0
  fi
  case "$_gen" in
    /tmp|/tmp/*)
      return 0
      ;;
  esac

  die "generated dir must be under --prefix, --data-dir, or /tmp: $_gen"
}

validate_service_root() {
  if [ -z "$SERVICE_ROOT" ]; then
    die "service root must not be empty"
  fi
  case "$SERVICE_ROOT" in
    /*) ;;
    *)
      die "service root must be an absolute path: $SERVICE_ROOT"
      ;;
  esac
  case "$SERVICE_ROOT" in
    .|/etc|/etc/*|/usr|/usr/*|/lib|/lib/*|/opt|/opt/*|/srv|/srv/*)
      die "refusing unsafe service root: $SERVICE_ROOT"
      ;;
  esac
}

validate_package_manager_flag() {
  case "$PACKAGE_MANAGER" in
    auto|apt|none) ;;
    *) die "unsupported --package-manager: $PACKAGE_MANAGER (expected auto, apt, or none)" ;;
  esac
}

resolve_package_manager() {
  validate_package_manager_flag
  if [ "$NO_OS_PACKAGES" -eq 1 ] || [ "$PACKAGE_MANAGER" = "none" ]; then
    PKG_INSTALL_ENABLED=0
    RESOLVED_PKG_MGR="none"
    return 0
  fi
  case "$PACKAGE_MANAGER" in
    auto)
      if command_exists apt-get; then
        PKG_INSTALL_ENABLED=1
        RESOLVED_PKG_MGR="apt"
        return 0
      fi
      die "apt-get not found; use --no-os-packages or --package-manager none to skip OS package install"
      ;;
    apt)
      if command_exists apt-get; then
        PKG_INSTALL_ENABLED=1
        RESOLVED_PKG_MGR="apt"
        return 0
      fi
      die "apt-get not found but --package-manager apt was requested"
      ;;
  esac
}

manual_package_guidance() {
  echo "Install these packages manually: $APT_PACKAGES" >&2
}

apt_install_command() {
  echo "apt-get install -y $APT_PACKAGES"
}

print_os_prerequisite_steps() {
  echo "OS prerequisite steps:"
  if [ "$PKG_INSTALL_ENABLED" -eq 1 ]; then
    if is_root; then
      echo "  Run apt-get update"
      echo "  Run $(apt_install_command)"
    else
      echo "  Run sudo apt-get update"
      echo "  Run sudo $(apt_install_command)"
    fi
    echo "  Packages: $APT_PACKAGES"
  else
    echo "  Skip apt package install (--no-os-packages or --package-manager none)"
    echo "  Verify commands exist: git python3 curl"
    echo "  Verify python3 -m venv works"
  fi
}

install_os_prerequisites() {
  if [ "$PKG_INSTALL_ENABLED" -eq 0 ]; then
    return 0
  fi
  if ! run_as_root apt-get update; then
    die "apt-get update failed"
  fi
  # shellcheck disable=SC2086
  if ! run_as_root apt-get install -y $APT_PACKAGES; then
    die "apt-get install failed"
  fi
}

service_dest() {
  _suffix="$1"
  if [ "$SERVICE_ROOT" = "/" ]; then
    echo "$_suffix"
    return 0
  fi
  echo "$SERVICE_ROOT$_suffix"
}

run_privileged() {
  if [ "$SERVICE_ROOT" = "/" ]; then
    if is_root; then
      "$@"
      return $?
    fi
    if command_exists sudo; then
      sudo "$@"
      return $?
    fi
    die "root or sudo required to install services under /"
  fi
  "$@"
}

timestamp_for_backup() {
  date +%Y%m%d%H%M%S
}

install_service_pair() {
  _filename="$1"
  _dest_suffix="$2"
  _mode="$3"
  _src="$GENERATED_DIR/$_filename"
  _dest=$(service_dest "$_dest_suffix")
  if [ ! -f "$_src" ]; then
    die "missing generated service file: $_src"
  fi
  _dest_dir=$(dirname "$_dest")
  run_privileged mkdir -p "$_dest_dir"
  if [ -f "$_dest" ]; then
    _ts=$(timestamp_for_backup)
    run_privileged cp "$_dest" "$_dest.bak.$_ts"
  fi
  run_privileged cp "$_src" "$_dest"
  run_privileged chmod "$_mode" "$_dest"
}

install_rag_service_files() {
  install_service_pair ark-rag.env /etc/ark-pi/ark-rag.env 0640
  install_service_pair ark-rag.service /etc/systemd/system/ark-rag.service 0644
}

install_llm_service_files() {
  install_service_pair ark-llm.env /etc/ark-pi/ark-llm.env 0640
  install_service_pair ark-llm.service /etc/systemd/system/ark-llm.service 0644
}

print_service_file_plan() {
  _filename="$1"
  _dest_suffix="$2"
  _mode="$3"
  _dest=$(service_dest "$_dest_suffix")
  echo "  Copy $GENERATED_DIR/$_filename -> $_dest (mode $_mode)"
  echo "    backup existing destination to $_dest.bak.TIMESTAMP if present"
}

print_rag_service_plan() {
  print_service_file_plan ark-rag.env /etc/ark-pi/ark-rag.env 0640
  print_service_file_plan ark-rag.service /etc/systemd/system/ark-rag.service 0644
}

print_llm_service_plan() {
  print_service_file_plan ark-llm.env /etc/ark-pi/ark-llm.env 0640
  print_service_file_plan ark-llm.service /etc/systemd/system/ark-llm.service 0644
}

service_unit_names_for_role() {
  case "$ROLE" in
    rag) echo ark-rag.service ;;
    llm) echo ark-llm.service ;;
    both)
      echo ark-rag.service
      echo ark-llm.service
      ;;
  esac
}

print_common_summary() {
  echo "Ark Pi install bootstrap"
  echo ""
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run: no host changes will be made."
  elif [ "$INSTALL_SERVICES" -eq 1 ]; then
    echo "App bootstrap + service file install."
  else
    echo "App bootstrap: writes under --prefix, --data-dir, and --generated-dir."
  fi
  echo ""
  echo "Detected OS:           $OS"
  echo "Detected architecture: $ARCH"
  echo "Role:                  $ROLE"
  echo "Repo:                  $REPO"
  echo "Branch:                $BRANCH"
  echo "Prefix:                $PREFIX"
  echo "Data dir:              $DATA_DIR"
  echo "Generated dir:         $GENERATED_DIR"
  echo "Install services:      $([ "$INSTALL_SERVICES" -eq 1 ] && echo yes || echo no)"
  echo "Service root:          $SERVICE_ROOT"
  echo "Package manager:       $PACKAGE_MANAGER (resolved: $RESOLVED_PKG_MGR)"
  if [ "$PKG_INSTALL_ENABLED" -eq 1 ]; then
    echo "OS packages:           install via apt"
    if is_root; then
      echo "Sudo for packages:     no (running as root)"
    else
      echo "Sudo for packages:     yes"
    fi
  else
    echo "OS packages:           skip (check only)"
  fi
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
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    if [ "$NO_ENABLE" -eq 1 ]; then
      echo "Enable services:       no (--no-enable)"
    else
      echo "Enable services:       yes (when service root is /)"
    fi
    if [ "$NO_START" -eq 1 ]; then
      echo "Start services:        no (--no-start)"
    else
      echo "Start services:        yes (when service root is /)"
    fi
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

render_deploy_command() {
  _deploy_role=$(deploy_role_for_install_role)
  echo "$PREFIX/.venv/bin/ark deploy render --output-dir $GENERATED_DIR --role $_deploy_role --force"
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
  echo "  6. Run $(render_deploy_command)"
}

print_service_install_steps() {
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    return 0
  fi
  echo ""
  echo "Service file install steps:"
  case "$ROLE" in
    rag) print_rag_service_plan ;;
    llm) print_llm_service_plan ;;
    both)
      print_rag_service_plan
      print_llm_service_plan
      ;;
  esac
  if [ "$SERVICE_ROOT" = "/" ]; then
    echo "  systemctl daemon-reload"
    if [ "$NO_ENABLE" -eq 0 ]; then
      for _unit in $(service_unit_names_for_role); do
        echo "  systemctl enable $_unit"
      done
    fi
    if [ "$NO_START" -eq 0 ]; then
      for _unit in $(service_unit_names_for_role); do
        echo "  systemctl start $_unit"
      done
    fi
  else
    echo "  Skip systemctl (service root is not /)"
  fi
}

print_future_service_steps() {
  echo ""
  echo "Not automated by install.sh:"
  echo "  - Install llama.cpp or download GGUF models"
  echo "  - Configure WiFi AP or network"
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    echo "  - Install env/systemd files (use --install-services to opt in)"
  fi
  if [ "$PKG_INSTALL_ENABLED" -eq 0 ]; then
    echo "  - Non-apt OS package install (use apt-based host or install packages manually)"
  fi
}

print_dry_run_footer() {
  echo ""
  echo "No changes were made."
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    echo "Use --install-services to install rendered env/systemd files."
  fi
  echo "Manual guide: docs/deployment/two-pi-manual.md"
}

print_plan() {
  print_common_summary
  print_os_prerequisite_steps
  echo ""
  print_app_bootstrap_steps
  print_service_install_steps
  print_future_service_steps
  print_dry_run_footer
}

check_dependencies() {
  if ! command_exists git; then
    manual_package_guidance
    die "git not found"
  fi
  if ! command_exists python3; then
    manual_package_guidance
    die "python3 not found"
  fi
  if ! command_exists curl; then
    manual_package_guidance
    die "curl not found"
  fi
  if ! python3 -m venv --help >/dev/null 2>&1; then
    manual_package_guidance
    die "python3 -m venv is not available; install python3-venv"
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
  echo "  Prefix:           $PREFIX"
  echo "  Data dir:         $DATA_DIR"
  echo "  Generated dir:    $GENERATED_DIR"
  echo "  Role:             $ROLE"
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    echo "  Install services: yes (service root: $SERVICE_ROOT)"
  else
    echo "  Install services: no"
  fi
  if [ "$PKG_INSTALL_ENABLED" -eq 1 ]; then
    echo "  OS packages:    install via apt ($APT_PACKAGES)"
  else
    echo "  OS packages:    skip (check only)"
  fi
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

run_deploy_render() {
  _deploy_role=$(deploy_role_for_install_role)
  _ark="$PREFIX/.venv/bin/ark"
  if [ ! -x "$_ark" ]; then
    die "ark CLI missing at $_ark"
  fi
  mkdir -p "$GENERATED_DIR"
  if ! "$_ark" deploy render --output-dir "$GENERATED_DIR" --role "$_deploy_role" --force; then
    die "ark deploy render failed"
  fi
}

validate_generated_service_files() {
  case "$ROLE" in
    rag)
      [ -f "$GENERATED_DIR/ark-rag.env" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.env"
      [ -f "$GENERATED_DIR/ark-rag.service" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.service"
      ;;
    llm)
      [ -f "$GENERATED_DIR/ark-llm.env" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.env"
      [ -f "$GENERATED_DIR/ark-llm.service" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.service"
      ;;
    both)
      [ -f "$GENERATED_DIR/ark-rag.env" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.env"
      [ -f "$GENERATED_DIR/ark-rag.service" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.service"
      [ -f "$GENERATED_DIR/ark-llm.env" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.env"
      [ -f "$GENERATED_DIR/ark-llm.service" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.service"
      ;;
  esac
}

install_service_files() {
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    return 0
  fi
  validate_generated_service_files
  case "$ROLE" in
    rag) install_rag_service_files ;;
    llm) install_llm_service_files ;;
    both)
      install_rag_service_files
      install_llm_service_files
      ;;
  esac
}

run_systemctl() {
  if ! run_privileged systemctl "$@"; then
    die "systemctl $* failed"
  fi
}

run_systemctl_actions() {
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    return 0
  fi
  if [ "$SERVICE_ROOT" != "/" ]; then
    echo ""
    echo "Service files installed under redirected root: $SERVICE_ROOT"
    echo "Skipping systemctl (service root is not /)."
    return 0
  fi
  run_systemctl daemon-reload
  if [ "$NO_ENABLE" -eq 0 ]; then
    for _unit in $(service_unit_names_for_role); do
      run_systemctl enable "$_unit"
    done
  fi
  if [ "$NO_START" -eq 0 ]; then
    for _unit in $(service_unit_names_for_role); do
      run_systemctl start "$_unit"
    done
  fi
}

print_validation_commands() {
  _deploy_role=$(deploy_role_for_install_role)
  _ark="$PREFIX/.venv/bin/ark"
  echo ""
  echo "Validation commands:"
  echo "  $_ark preflight"
  echo "  $_ark llm status"
  echo "  $_ark llm test --llm-backend mock"
  echo "  $_ark deploy preflight --generated-dir $GENERATED_DIR --role $_deploy_role"
  echo "  $_ark deploy plan --generated-dir $GENERATED_DIR --role $_deploy_role"
  echo "  curl http://127.0.0.1:8000/healthz"
  echo "  curl http://127.0.0.1:8000/api/status"
  echo ""
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    echo "Review installed env and systemd files under $SERVICE_ROOT before production use."
    if [ "$SERVICE_ROOT" != "/" ]; then
      echo "Service files are under redirected root for review/testing."
    fi
  else
    echo "Review generated env and systemd files before installing services."
    echo "Use --install-services to install rendered files."
  fi
  echo "llama.cpp, models, and network setup remain manual."
  echo "For full deployment, see docs/deployment/two-pi-manual.md"
}

print_success_message() {
  echo ""
  echo "App bootstrap complete."
  echo "Prefix:            $PREFIX"
  echo "Data dir:          $DATA_DIR"
  echo "Generated dir:     $GENERATED_DIR"
  echo "Role:              $ROLE"
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    echo "Service root:      $SERVICE_ROOT"
    echo "Installed service files:"
    case "$ROLE" in
      rag)
        echo "  $(service_dest /etc/ark-pi/ark-rag.env)"
        echo "  $(service_dest /etc/systemd/system/ark-rag.service)"
        ;;
      llm)
        echo "  $(service_dest /etc/ark-pi/ark-llm.env)"
        echo "  $(service_dest /etc/systemd/system/ark-llm.service)"
        ;;
      both)
        echo "  $(service_dest /etc/ark-pi/ark-rag.env)"
        echo "  $(service_dest /etc/systemd/system/ark-rag.service)"
        echo "  $(service_dest /etc/ark-pi/ark-llm.env)"
        echo "  $(service_dest /etc/systemd/system/ark-llm.service)"
        ;;
    esac
  fi
  echo "Created data directories:"
  for _dir in $(data_dirs_for_role); do
    echo "  $_dir"
  done
  print_validation_commands
}

run_bootstrap() {
  install_os_prerequisites
  check_dependencies
  check_path_writable "$PREFIX" "prefix"
  check_path_writable "$DATA_DIR" "data dir"
  check_path_writable "$GENERATED_DIR" "generated dir"
  ensure_clean_prefix
  clone_or_update_repo
  create_venv_and_install
  create_data_dirs
  run_deploy_render
  install_service_files
  run_systemctl_actions
  print_success_message
}

main() {
  parse_args "$@"
  set_generated_dir_default
  detect_platform
  if [ -z "$ROLE" ]; then
    if is_interactive; then
      prompt_role
    else
      die "--role is required in non-interactive mode (use --role rag|llm|both)"
    fi
  fi
  validate_role
  validate_generated_dir
  validate_service_root
  resolve_package_manager

  if [ "$DRY_RUN" -eq 1 ]; then
    print_plan
    exit 0
  fi

  print_common_summary
  print_os_prerequisite_steps
  echo ""
  print_app_bootstrap_steps
  print_service_install_steps
  print_future_service_steps
  echo ""
  require_confirmation_for_mutation
  run_bootstrap
}

main "$@"
