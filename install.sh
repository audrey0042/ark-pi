#!/bin/sh
#
# Ark Pi install bootstrap (v5).
# App bootstrap, deploy render, optional service install, apt OS prerequisites,
# post-install validation and --validate-only mode.
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
VALIDATE_ONLY=0
NO_VALIDATE=0
VALIDATION_FAILED=0
VALIDATION_WARNED=0

INSTALL_OWNER=""
INSTALL_GROUP=""

OS=""
ARCH=""

APT_PACKAGES="ca-certificates curl git python3 python3-venv python3-pip python3-dev build-essential pkg-config rsync unzip jq"

usage() {
  cat <<'EOF'
Ark Pi install bootstrap

Bootstraps the Ark Pi app: clone/update repo, Python venv, pip install -e,
role-specific data directories, deployment template render, and optional
env/systemd file install.

Does not install llama.cpp or download models. On Debian-family hosts,
can install RAG Pi apt prerequisites (git, python3, python3-venv, python3-pip, build tools, etc.).

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
  --validate-only           Validate an existing install; no mutations
  --no-validate             Skip post-install validation after real install
  --help                    Show this help

Examples:
  sh install.sh --role rag --dry-run
  sh install.sh --role rag --no-os-packages --dry-run
  sh install.sh --role rag --install-services --dry-run
  sh install.sh --role rag --validate-only --prefix /tmp/ark-pi-prefix --data-dir /tmp/ark-pi-data --generated-dir /tmp/ark-pi-generated
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
      --validate-only)
        VALIDATE_ONLY=1
        shift
        ;;
      --no-validate)
        NO_VALIDATE=1
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
  _parent=$(path_dirname "$_path")
  _base=$(path_basename "$_path")
  if [ -e "$_parent" ]; then
    _resolved_parent=$(cd "$_parent" && pwd -P)
    echo "$_resolved_parent/$_base"
    return 0
  fi
  echo "$_path"
}

path_dirname() {
  _path="$1"
  case "$_path" in
    /*/*) echo "${_path%/*}" ;;
    /*) echo "/" ;;
    */*) echo "${_path%/*}" ;;
    *) echo "." ;;
  esac
}

path_basename() {
  _path="$1"
  case "$_path" in
    */*) echo "${_path##*/}" ;;
    *) echo "$_path" ;;
  esac
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

# Test-only: map /opt and /srv paths into ARK_PI_INSTALL_TEST_SYSTEM_ROOT for offline tests.
map_install_path() {
  _path="$1"
  if [ -n "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT:-}" ]; then
    case "$_path" in
      /opt|/opt/*)
        echo "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT}/opt${_path#/opt}"
        return 0
        ;;
      /srv|/srv/*)
        echo "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT}/srv${_path#/srv}"
        return 0
        ;;
    esac
  fi
  echo "$_path"
}

validate_install_paths() {
  validate_single_install_path "$PREFIX" "prefix"
  validate_single_install_path "$DATA_DIR" "data dir"
}

validate_single_install_path() {
  _path="$1"
  _label="$2"
  case "$_path" in
    /*) ;;
    *)
      die "$_label must be an absolute path: $_path"
      ;;
  esac
  case "$_path" in
    /|/opt|/usr|/etc|/srv|/lib|/var|/bin|/sbin)
      die "refusing unsafe install path: $_path"
      ;;
  esac
}

resolve_install_owner() {
  if is_root; then
    if [ -n "${SUDO_USER:-}" ]; then
      INSTALL_OWNER="$SUDO_USER"
      if INSTALL_GROUP=$(id -gn "$SUDO_USER" 2>/dev/null); then
        :
      elif [ -n "${SUDO_GID:-}" ]; then
        INSTALL_GROUP=$(getent group "$SUDO_GID" 2>/dev/null | cut -d: -f1)
      fi
      if [ -z "${INSTALL_GROUP:-}" ]; then
        die "cannot determine group for sudo user: $SUDO_USER"
      fi
      return 0
    fi
  fi
  INSTALL_OWNER=$(id -un 2>/dev/null || true)
  INSTALL_GROUP=$(id -gn 2>/dev/null || true)
  if [ -z "${INSTALL_OWNER:-}" ] || [ -z "${INSTALL_GROUP:-}" ]; then
    die "cannot determine install directory owner"
  fi
}

install_path_needs_privileged_prep() {
  _logical_path="$1"
  _which="$2"
  if [ "$_which" = "prefix" ] && [ "${ARK_PI_INSTALL_TEST_UNWRITABLE_PREFIX_PARENT:-0}" = "1" ]; then
    return 0
  fi
  if [ "$_which" = "data-dir" ] && [ "${ARK_PI_INSTALL_TEST_UNWRITABLE_DATA_DIR_PARENT:-0}" = "1" ]; then
    return 0
  fi
  _path=$(map_install_path "$_logical_path")
  if [ -e "$_path" ]; then
    if [ -w "$_path" ]; then
      return 1
    fi
    return 0
  fi
  _parent=$(path_dirname "$_path")
  while [ ! -e "$_parent" ]; do
    _parent=$(path_dirname "$_parent")
  done
  if [ -w "$_parent" ]; then
    return 1
  fi
  return 0
}

prepare_install_owned_path() {
  _logical_path="$1"
  _label="$2"
  _which="$3"
  if ! install_path_needs_privileged_prep "$_logical_path" "$_which"; then
    return 0
  fi
  resolve_install_owner
  _path=$(map_install_path "$_logical_path")
  if [ ! -e "$_path" ]; then
    if ! run_as_root mkdir -p "$_path"; then
      die "failed to create $_label: $_logical_path"
    fi
    if ! run_as_root chown "$INSTALL_OWNER:$INSTALL_GROUP" "$_path"; then
      die "failed to chown $_label to $INSTALL_OWNER:$INSTALL_GROUP"
    fi
    return 0
  fi
  if ! run_as_root chown -R "$INSTALL_OWNER:$INSTALL_GROUP" "$_path"; then
    die "failed to chown $_label to $INSTALL_OWNER:$INSTALL_GROUP"
  fi
}

prepare_install_owned_paths() {
  prepare_install_owned_path "$PREFIX" "prefix" "prefix"
  prepare_install_owned_path "$DATA_DIR" "data dir" "data-dir"
}

print_install_path_ownership_steps() {
  echo "Install path ownership steps:"
  _owner_label="(resolved before install)"
  if _owner=$(id -un 2>/dev/null) && _group=$(id -gn 2>/dev/null); then
    _owner_label="$_owner:$_group"
  fi
  echo "  Install owner:       $_owner_label"
  _print_install_path_ownership_plan "$PREFIX" "prefix" "prefix"
  _print_install_path_ownership_plan "$DATA_DIR" "data dir" "data-dir"
}

_print_install_path_ownership_plan() {
  _logical_path="$1"
  _label="$2"
  _which="$3"
  _owner_label="USER:GROUP"
  if _owner=$(id -un 2>/dev/null) && _group=$(id -gn 2>/dev/null); then
    _owner_label="$_owner:$_group"
  fi
  if install_path_needs_privileged_prep "$_logical_path" "$_which"; then
    _mapped=$(map_install_path "$_logical_path")
    echo "  Prepare $_label:    $_logical_path (sudo required)"
    if [ ! -e "$_mapped" ]; then
      if is_root; then
        echo "  Run mkdir -p $_logical_path"
        echo "  Run chown $_owner_label $_logical_path"
      else
        echo "  Run sudo mkdir -p $_logical_path"
        echo "  Run sudo chown $_owner_label $_logical_path"
      fi
    else
      if is_root; then
        echo "  Run chown -R $_owner_label $_logical_path"
      else
        echo "  Run sudo chown -R $_owner_label $_logical_path"
      fi
    fi
  else
    echo "  Prepare $_label:    $_logical_path (writable; no sudo needed)"
  fi
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
  _generated=$(map_install_path "$GENERATED_DIR")
  _src="$_generated/$_filename"
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
  if [ "$VALIDATE_ONLY" -eq 1 ]; then
    echo "Validate only:         yes"
  else
    echo "Validate only:         no"
  fi
  if [ "$NO_VALIDATE" -eq 1 ]; then
    echo "Post-install validate: no (--no-validate)"
  elif [ "$VALIDATE_ONLY" -eq 1 ]; then
    echo "Post-install validate: n/a"
  else
    echo "Post-install validate: yes"
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
  print_install_path_ownership_steps
  echo ""
  if [ "$VALIDATE_ONLY" -eq 1 ]; then
    print_validation_plan_steps
  else
    print_app_bootstrap_steps
    print_service_install_steps
    print_future_service_steps
    print_post_install_validation_note
  fi
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
  _parent=$(path_dirname "$_path")
  while [ ! -e "$_parent" ]; do
    _parent=$(path_dirname "$_parent")
  done
  if [ ! -w "$_parent" ]; then
    die "cannot create $_label under unwritable parent: $_parent"
  fi
}

prefix_is_empty() {
  _pref=$(map_install_path "$PREFIX")
  if [ ! -d "$_pref" ]; then
    return 0
  fi
  if [ -z "$(ls -A "$_pref" 2>/dev/null)" ]; then
    return 0
  fi
  return 1
}

ensure_clean_prefix() {
  _pref=$(map_install_path "$PREFIX")
  if [ -e "$_pref" ] && [ ! -d "$_pref" ]; then
    die "prefix exists but is not a directory: $PREFIX"
  fi
  if [ ! -e "$_pref" ]; then
    return 0
  fi
  if [ -d "$_pref/.git" ]; then
    if [ -n "$(git -C "$_pref" status --porcelain 2>/dev/null)" ]; then
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
  _pref=$(map_install_path "$PREFIX")
  if [ ! -d "$_pref" ]; then
    _parent=$(path_dirname "$_pref")
    mkdir -p "$_parent"
    git clone --branch "$BRANCH" "$REPO" "$_pref"
    return 0
  fi
  if [ -d "$_pref/.git" ]; then
    git -C "$_pref" fetch origin "$BRANCH"
    git -C "$_pref" checkout "$BRANCH"
    return 0
  fi
  git clone --branch "$BRANCH" "$REPO" "$_pref"
}

create_venv_and_install() {
  _pref=$(map_install_path "$PREFIX")
  _venv="$_pref/.venv"
  if [ ! -d "$_venv" ]; then
    python3 -m venv "$_venv"
  fi
  "$_venv/bin/pip" install -e "$_pref"
  "$_venv/bin/ark" --help >/dev/null
}

create_data_dirs() {
  for _dir in $(data_dirs_for_role); do
    mkdir -p "$(map_install_path "$_dir")"
  done
}

run_deploy_render() {
  _deploy_role=$(deploy_role_for_install_role)
  _pref=$(map_install_path "$PREFIX")
  _generated=$(map_install_path "$GENERATED_DIR")
  _ark="$_pref/.venv/bin/ark"
  if [ ! -x "$_ark" ]; then
    die "ark CLI missing at $_ark"
  fi
  mkdir -p "$_generated"
  if ! "$_ark" deploy render --output-dir "$_generated" --role "$_deploy_role" --force; then
    die "ark deploy render failed"
  fi
}

validate_generated_service_files() {
  _generated=$(map_install_path "$GENERATED_DIR")
  case "$ROLE" in
    rag)
      [ -f "$_generated/ark-rag.env" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.env"
      [ -f "$_generated/ark-rag.service" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.service"
      ;;
    llm)
      [ -f "$_generated/ark-llm.env" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.env"
      [ -f "$_generated/ark-llm.service" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.service"
      ;;
    both)
      [ -f "$_generated/ark-rag.env" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.env"
      [ -f "$_generated/ark-rag.service" ] || die "missing generated service file: $GENERATED_DIR/ark-rag.service"
      [ -f "$_generated/ark-llm.env" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.env"
      [ -f "$_generated/ark-llm.service" ] || die "missing generated service file: $GENERATED_DIR/ark-llm.service"
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

deploy_templates_for_role() {
  case "$ROLE" in
    rag)
      echo ark-rag.env
      echo ark-rag.service
      ;;
    llm)
      echo ark-llm.env
      echo ark-llm.service
      ;;
    both)
      echo ark-rag.env
      echo ark-rag.service
      echo ark-llm.env
      echo ark-llm.service
      ;;
  esac
}

service_env_files_for_role() {
  case "$ROLE" in
    rag) echo ark-rag.env ;;
    llm) echo ark-llm.env ;;
    both)
      echo ark-rag.env
      echo ark-llm.env
      ;;
  esac
}

service_unit_files_for_role() {
  case "$ROLE" in
    rag) echo ark-rag.service ;;
    llm) echo ark-llm.service ;;
    both)
      echo ark-rag.service
      echo ark-llm.service
      ;;
  esac
}

should_validate_services() {
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    return 0
  fi
  for _env in $(service_env_files_for_role); do
    if [ -f "$(service_dest "/etc/ark-pi/$_env")" ]; then
      return 0
    fi
  done
  for _unit in $(service_unit_files_for_role); do
    if [ -f "$(service_dest "/etc/systemd/system/$_unit")" ]; then
      return 0
    fi
  done
  return 1
}

validation_env_service_path() {
  _role="$1"
  case "$_role" in
    rag) service_dest /etc/ark-pi/ark-rag.env ;;
    llm) service_dest /etc/ark-pi/ark-llm.env ;;
    *) die "internal validation role error: $_role" ;;
  esac
}

validation_env_generated_path() {
  _role="$1"
  _generated=$(map_install_path "$GENERATED_DIR")
  case "$_role" in
    rag) echo "$_generated/ark-rag.env" ;;
    llm) echo "$_generated/ark-llm.env" ;;
    *) die "internal validation role error: $_role" ;;
  esac
}

validation_env_display_path() {
  _role="$1"
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    validation_env_service_path "$_role"
    return 0
  fi
  case "$_role" in
    rag) echo "$GENERATED_DIR/ark-rag.env" ;;
    llm) echo "$GENERATED_DIR/ark-llm.env" ;;
    *) die "internal validation role error: $_role" ;;
  esac
}

resolve_validation_env_file() {
  _role="$1"
  _service=$(validation_env_service_path "$_role")
  _generated=$(validation_env_generated_path "$_role")
  VALIDATION_ENV_FALLBACK=0

  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    if [ -f "$_service" ]; then
      VALIDATION_RESOLVED_ENV_FILE="$_service"
      return 0
    fi
    return 1
  fi

  if [ -f "$_generated" ]; then
    VALIDATION_RESOLVED_ENV_FILE="$_generated"
    return 0
  fi

  if [ "$VALIDATE_ONLY" -eq 1 ] && [ -f "$_service" ]; then
    VALIDATION_RESOLVED_ENV_FILE="$_service"
    VALIDATION_ENV_FALLBACK=1
    return 0
  fi

  return 1
}

export_allowed_ark_env_pair() {
  _key="$1"
  _value="$2"
  case "$_key" in
    ARK_ROLE) ARK_ROLE="$_value"; export ARK_ROLE ;;
    ARK_HOST) ARK_HOST="$_value"; export ARK_HOST ;;
    ARK_PORT) ARK_PORT="$_value"; export ARK_PORT ;;
    ARK_DATA_DIR) ARK_DATA_DIR="$_value"; export ARK_DATA_DIR ;;
    ARK_WORKSPACE_DIR) ARK_WORKSPACE_DIR="$_value"; export ARK_WORKSPACE_DIR ;;
    ARK_SOURCE_DIR) ARK_SOURCE_DIR="$_value"; export ARK_SOURCE_DIR ;;
    ARK_INDEX_DIR) ARK_INDEX_DIR="$_value"; export ARK_INDEX_DIR ;;
    ARK_INDEX_BACKEND) ARK_INDEX_BACKEND="$_value"; export ARK_INDEX_BACKEND ;;
    ARK_CHROMA_DIR) ARK_CHROMA_DIR="$_value"; export ARK_CHROMA_DIR ;;
    ARK_COLLECTION_NAME) ARK_COLLECTION_NAME="$_value"; export ARK_COLLECTION_NAME ;;
    ARK_EMBEDDING_MODEL) ARK_EMBEDDING_MODEL="$_value"; export ARK_EMBEDDING_MODEL ;;
    ARK_LLM_BACKEND) ARK_LLM_BACKEND="$_value"; export ARK_LLM_BACKEND ;;
    ARK_LLM_BASE_URL) ARK_LLM_BASE_URL="$_value"; export ARK_LLM_BASE_URL ;;
    ARK_LLM_MODEL) ARK_LLM_MODEL="$_value"; export ARK_LLM_MODEL ;;
    ARK_LLM_TIMEOUT_SECONDS) ARK_LLM_TIMEOUT_SECONDS="$_value"; export ARK_LLM_TIMEOUT_SECONDS ;;
    ARK_LLM_MAX_TOKENS) ARK_LLM_MAX_TOKENS="$_value"; export ARK_LLM_MAX_TOKENS ;;
    ARK_LLM_TEMPERATURE) ARK_LLM_TEMPERATURE="$_value"; export ARK_LLM_TEMPERATURE ;;
    ARK_MAX_IMPORT_BYTES) ARK_MAX_IMPORT_BYTES="$_value"; export ARK_MAX_IMPORT_BYTES ;;
    ARK_LLAMA_HOST) ARK_LLAMA_HOST="$_value"; export ARK_LLAMA_HOST ;;
    ARK_LLAMA_PORT) ARK_LLAMA_PORT="$_value"; export ARK_LLAMA_PORT ;;
    ARK_MODEL_DIR) ARK_MODEL_DIR="$_value"; export ARK_MODEL_DIR ;;
    ARK_MODEL_PATH) ARK_MODEL_PATH="$_value"; export ARK_MODEL_PATH ;;
    ARK_CONTEXT_SIZE) ARK_CONTEXT_SIZE="$_value"; export ARK_CONTEXT_SIZE ;;
    ARK_THREADS) ARK_THREADS="$_value"; export ARK_THREADS ;;
    ARK_LLM_HOST) ARK_LLM_HOST="$_value"; export ARK_LLM_HOST ;;
    ARK_LLM_PORT) ARK_LLM_PORT="$_value"; export ARK_LLM_PORT ;;
    ARK_LLAMACPP_SERVER_BIN) ARK_LLAMACPP_SERVER_BIN="$_value"; export ARK_LLAMACPP_SERVER_BIN ;;
    ARK_LLAMACPP_MODEL_PATH) ARK_LLAMACPP_MODEL_PATH="$_value"; export ARK_LLAMACPP_MODEL_PATH ;;
    ARK_LLAMACPP_CTX_SIZE) ARK_LLAMACPP_CTX_SIZE="$_value"; export ARK_LLAMACPP_CTX_SIZE ;;
    ARK_LLAMACPP_THREADS) ARK_LLAMACPP_THREADS="$_value"; export ARK_LLAMACPP_THREADS ;;
    ARK_LLAMACPP_EXTRA_ARGS) ARK_LLAMACPP_EXTRA_ARGS="$_value"; export ARK_LLAMACPP_EXTRA_ARGS ;;
    *) return 1 ;;
  esac
  return 0
}

load_role_env_for_validation() {
  _path="$1"
  _role="$2"
  _unknown=""
  _unknown_sep=""

  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      ''|'#'*) continue ;;
    esac
    case "$_line" in
      *=*) ;;
      *)
        record_validation_check role_env_parse fail "malformed line in $_path: $_line"
        return 1
        ;;
    esac
    _key=${_line%%=*}
    _value=${_line#*=}
    if export_allowed_ark_env_pair "$_key" "$_value"; then
      continue
    fi
    _unknown="$_unknown$_unknown_sep$_key"
    _unknown_sep=", "
  done < "$_path"

  if [ -n "$_unknown" ]; then
    record_validation_check role_env_unknown_keys warning "unknown keys in $_path (ignored): $_unknown"
  fi
  return 0
}

run_ark_with_role_env() {
  _role="$1"
  _ark="$2"
  shift 2
  _display=$(validation_env_display_path "$_role")

  if ! resolve_validation_env_file "$_role"; then
    record_validation_check role_env_file fail "missing env file for role $_role (expected under $_display)"
    return 1
  fi
  _env_file="$VALIDATION_RESOLVED_ENV_FILE"
  if [ "$VALIDATION_ENV_FALLBACK" -eq 1 ]; then
    record_validation_check role_env_file warning "generated env missing; using service env: $_env_file"
  fi
  if ! load_role_env_for_validation "$_env_file" "$_role"; then
    return 1
  fi
  if "$_ark" "$@" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

reset_validation_state() {
  VALIDATION_FAILED=0
  VALIDATION_WARNED=0
}

record_validation_check() {
  _id="$1"
  _status="$2"
  _message="$3"
  printf "  [%s] %s: %s\n" "$_status" "$_id" "$_message"
  case "$_status" in
    pass) ;;
    warning) VALIDATION_WARNED=1 ;;
    fail) VALIDATION_FAILED=1 ;;
    *)
      die "internal validation status error: $_status"
      ;;
  esac
}

check_deploy_templates_exist() {
  _generated=$(map_install_path "$GENERATED_DIR")
  _missing=0
  for _file in $(deploy_templates_for_role); do
    if [ -f "$_generated/$_file" ]; then
      continue
    fi
    case "$_file" in
      ark-rag.env)
        if [ "$VALIDATE_ONLY" -eq 1 ] && [ -f "$(validation_env_service_path rag)" ]; then
          continue
        fi
        ;;
      ark-llm.env)
        if [ "$VALIDATE_ONLY" -eq 1 ] && [ -f "$(validation_env_service_path llm)" ]; then
          continue
        fi
        ;;
    esac
    _missing=1
  done
  if [ "$_missing" -eq 1 ]; then
    record_validation_check deploy_templates fail "missing deployment templates under $GENERATED_DIR for role $ROLE"
    return 1
  fi
  record_validation_check deploy_templates pass "deployment templates present for role $ROLE"
  return 0
}

check_systemctl_unit_state() {
  _unit="$1"
  if ! command_exists systemctl; then
    record_validation_check "systemctl_${_unit}" warning "systemctl not found; skipping unit state for $_unit"
    return 0
  fi
  if systemctl is-enabled "$_unit" >/dev/null 2>&1; then
    record_validation_check systemctl_enabled pass "$_unit is enabled"
  else
    record_validation_check systemctl_enabled warning "$_unit is not enabled"
  fi
  if systemctl is-active "$_unit" >/dev/null 2>&1; then
    record_validation_check systemctl_active pass "$_unit is active"
  else
    record_validation_check systemctl_active warning "$_unit is not active"
  fi
}

run_validation_checks() {
  _pref=$(map_install_path "$PREFIX")
  _data=$(map_install_path "$DATA_DIR")
  _generated=$(map_install_path "$GENERATED_DIR")
  _ark="$_pref/.venv/bin/ark"
  _deploy_role=$(deploy_role_for_install_role)

  reset_validation_state
  echo "Validation checks:"

  if [ -d "$_pref" ]; then
    record_validation_check prefix_exists pass "prefix exists: $PREFIX"
  else
    record_validation_check prefix_exists fail "prefix missing: $PREFIX"
  fi

  if [ -x "$_ark" ]; then
    record_validation_check venv_ark pass "ark CLI present: $PREFIX/.venv/bin/ark"
  else
    record_validation_check venv_ark fail "ark CLI missing or not executable: $PREFIX/.venv/bin/ark"
  fi

  if [ -x "$_ark" ]; then
    if "$_ark" --help >/dev/null 2>&1; then
      record_validation_check ark_help pass "ark --help succeeded"
    else
      record_validation_check ark_help fail "ark --help failed"
    fi
  fi

  if [ -d "$_data" ]; then
    record_validation_check data_dir pass "data dir exists: $DATA_DIR"
  else
    record_validation_check data_dir fail "data dir missing: $DATA_DIR"
  fi

  if [ -d "$_generated" ]; then
    record_validation_check generated_dir pass "generated dir exists: $GENERATED_DIR"
  else
    record_validation_check generated_dir fail "generated dir missing: $GENERATED_DIR"
  fi

  if [ -d "$_generated" ]; then
    check_deploy_templates_exist
  fi

  if [ -x "$_ark" ] && [ -d "$_generated" ]; then
    if "$_ark" deploy preflight --generated-dir "$_generated" --role "$_deploy_role" >/dev/null 2>&1; then
      record_validation_check deploy_preflight pass "ark deploy preflight succeeded"
    else
      record_validation_check deploy_preflight fail "ark deploy preflight failed for role $_deploy_role"
    fi
  fi

  case "$ROLE" in
    rag|both)
      if [ -d "$_data/data/workspace" ]; then
        record_validation_check rag_workspace_dir pass "RAG workspace dir exists"
      else
        record_validation_check rag_workspace_dir fail "RAG workspace dir missing: $DATA_DIR/data/workspace"
      fi
      if [ -d "$_data/data/sources" ]; then
        record_validation_check rag_source_dir pass "RAG sources dir exists"
      else
        record_validation_check rag_source_dir fail "RAG sources dir missing: $DATA_DIR/data/sources"
      fi
      if [ -x "$_ark" ]; then
        if run_ark_with_role_env rag "$_ark" preflight; then
          record_validation_check rag_preflight pass "ark preflight succeeded using $VALIDATION_RESOLVED_ENV_FILE"
        else
          if [ "$VALIDATION_FAILED" -eq 1 ]; then
            :
          else
            record_validation_check rag_preflight fail "ark preflight failed using $VALIDATION_RESOLVED_ENV_FILE"
          fi
        fi
        if run_ark_with_role_env rag "$_ark" llm status; then
          record_validation_check rag_llm_status pass "ark llm status succeeded using $VALIDATION_RESOLVED_ENV_FILE"
        else
          if [ "$VALIDATION_FAILED" -eq 1 ]; then
            :
          else
            record_validation_check rag_llm_status warning "ark llm status failed using $VALIDATION_RESOLVED_ENV_FILE (LLM may be offline)"
          fi
        fi
      fi
      ;;
  esac

  case "$ROLE" in
    llm|both)
      if [ -d "$_data/models" ]; then
        record_validation_check llm_model_dir pass "LLM model dir exists"
      else
        record_validation_check llm_model_dir fail "LLM model dir missing: $DATA_DIR/models"
      fi
      _gguf=$(find "$_data/models" -type f -name '*.gguf' 2>/dev/null | head -n 1)
      if [ -n "$_gguf" ]; then
        record_validation_check llm_model_file pass "GGUF model file found under $DATA_DIR/models"
      else
        record_validation_check llm_model_file warning "no GGUF model file under $DATA_DIR/models (manual step)"
      fi
      if [ -x "$_ark" ]; then
        if run_ark_with_role_env llm "$_ark" preflight; then
          record_validation_check llm_preflight pass "ark preflight succeeded using $VALIDATION_RESOLVED_ENV_FILE"
        else
          if [ "$VALIDATION_FAILED" -eq 1 ]; then
            :
          else
            record_validation_check llm_preflight fail "ark preflight failed using $VALIDATION_RESOLVED_ENV_FILE"
          fi
        fi
      fi
      ;;
  esac

  if should_validate_services; then
    _missing_env=0
    for _env in $(service_env_files_for_role); do
      _dest=$(service_dest "/etc/ark-pi/$_env")
      if [ ! -f "$_dest" ]; then
        _missing_env=1
        record_validation_check service_env_files fail "missing env file: $_dest"
      fi
    done
    if [ "$_missing_env" -eq 0 ]; then
      record_validation_check service_env_files pass "service env files present under $(service_dest /etc/ark-pi)"
    fi

    _missing_unit=0
    for _unit in $(service_unit_files_for_role); do
      _dest=$(service_dest "/etc/systemd/system/$_unit")
      if [ ! -f "$_dest" ]; then
        _missing_unit=1
        record_validation_check service_unit_files fail "missing unit file: $_dest"
      fi
    done
    if [ "$_missing_unit" -eq 0 ]; then
      record_validation_check service_unit_files pass "service unit files present under $(service_dest /etc/systemd/system)"
    fi

    if [ "$SERVICE_ROOT" = "/" ] || [ "${ARK_PI_INSTALL_TEST_SYSTEMCTL_ROOT:-0}" = "1" ]; then
      for _unit in $(service_unit_names_for_role); do
        check_systemctl_unit_state "$_unit"
      done
    fi
  fi
}

finalize_validation() {
  echo ""
  if [ "$VALIDATION_FAILED" -eq 1 ]; then
    echo "Validation: FAIL"
    return 1
  fi
  if [ "$VALIDATION_WARNED" -eq 1 ]; then
    echo "Validation: PASS (with warnings)"
    return 0
  fi
  echo "Validation: PASS"
  return 0
}

run_validation() {
  run_validation_checks
  finalize_validation
}

print_validation_plan_steps() {
  echo "Validation steps:"
  echo "  Check prefix, ark CLI, data dir, generated dir"
  echo "  Check deployment templates and ark deploy preflight for role $ROLE"
  case "$ROLE" in
    rag|both)
      echo "  Check RAG workspace/sources dirs, role-env-aware ark preflight, and ark llm status (warning if LLM offline)"
      ;;
  esac
  case "$ROLE" in
    llm|both)
      echo "  Check LLM model dir, warn if no GGUF model file, and role-env-aware ark preflight"
      ;;
  esac
  if should_validate_services; then
    echo "  Check service env/unit files under service root: $SERVICE_ROOT"
    if [ "$SERVICE_ROOT" = "/" ]; then
      echo "  Check systemctl is-enabled/is-active (read-only; warnings only)"
    else
      echo "  Skip systemctl (redirected service root)"
    fi
  else
    echo "  Skip service file checks (no --install-services and no files found)"
  fi
  echo "  Does not install llama.cpp, download models, or configure networking"
}

print_validate_only_plan() {
  print_common_summary
  echo ""
  print_validation_plan_steps
  print_dry_run_footer
}

print_post_install_validation_note() {
  echo ""
  if [ "$NO_VALIDATE" -eq 1 ]; then
    echo "Post-install validation: skipped (--no-validate)"
    echo "Run later:"
    echo "  sh install.sh --role $ROLE --validate-only --prefix $PREFIX --data-dir $DATA_DIR --generated-dir $GENERATED_DIR --service-root $SERVICE_ROOT"
    return 0
  fi
  echo "Post-install validation: will run after install unless --no-validate"
}

print_env_load_block() {
  _env_file="$1"
  echo "  set -a"
  echo "  . $_env_file"
  echo "  set +a"
}

print_role_validation_commands() {
  _role="$1"
  _ark="$2"
  _env_file=$(validation_env_display_path "$_role")
  echo "Role env ($_role): $_env_file"
  print_env_load_block "$_env_file"
  echo "  $_ark preflight"
  case "$_role" in
    rag) echo "  $_ark llm status" ;;
  esac
}

print_validation_commands() {
  _deploy_role=$(deploy_role_for_install_role)
  _ark="$PREFIX/.venv/bin/ark"
  echo ""
  echo "Validation commands (load role env first; bare ark preflight uses default config, not the service):"
  case "$ROLE" in
    rag)
      print_role_validation_commands rag "$_ark"
      ;;
    llm)
      print_role_validation_commands llm "$_ark"
      ;;
    both)
      print_role_validation_commands rag "$_ark"
      echo ""
      print_role_validation_commands llm "$_ark"
      ;;
  esac
  echo ""
  echo "One-liner example (rag):"
  _rag_env=$(validation_env_display_path rag)
  echo "  set -a; . $_rag_env; set +a; $_ark preflight"
  echo ""
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
  prepare_install_owned_paths
  check_path_writable "$(map_install_path "$GENERATED_DIR")" "generated dir"
  ensure_clean_prefix
  clone_or_update_repo
  create_venv_and_install
  create_data_dirs
  run_deploy_render
  install_service_files
  run_systemctl_actions
  print_success_message
  if [ "$NO_VALIDATE" -eq 0 ]; then
    echo ""
    echo "Running post-install validation..."
    if ! run_validation; then
      die "post-install validation failed"
    fi
  else
    print_post_install_validation_note
  fi
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
  if [ "$VALIDATE_ONLY" -eq 0 ]; then
    resolve_package_manager
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    print_plan
    exit 0
  fi

  if [ "$VALIDATE_ONLY" -eq 1 ]; then
    print_common_summary
    echo ""
    if ! run_validation; then
      exit 1
    fi
    exit 0
  fi

  validate_install_paths

  print_common_summary
  print_os_prerequisite_steps
  echo ""
  print_install_path_ownership_steps
  echo ""
  print_app_bootstrap_steps
  print_service_install_steps
  print_future_service_steps
  print_post_install_validation_note
  echo ""
  require_confirmation_for_mutation
  run_bootstrap
}

main "$@"
