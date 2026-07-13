#!/bin/sh
#
# Ark Pi install bootstrap (v5).
# App bootstrap, deploy render, optional service install, apt OS prerequisites,
# post-install validation and --validate-only mode.
# Optional llama.cpp build via --llama-build; optional GGUF download via --download-model.
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

LLAMA_BUILD=0
NO_LLAMA_BUILD=0
LLAMA_REPO="https://github.com/ggml-org/llama.cpp.git"
LLAMA_REF="master"
LLAMA_DIR=""
LLAMA_BUILD_DIR=""
LLAMA_BIN=""
MODEL_DIR=""
MODEL_PATH=""
REQUIRE_MODEL=0
DOWNLOAD_MODEL=0
MODEL_PRESET=""
MODEL_REPO=""
MODEL_FILE=""
MODEL_REVISION="main"
MODEL_URL=""
MODEL_SHA256=""
FORCE_MODEL_DOWNLOAD=0
MODEL_PRESET_LABEL=""
MODEL_SIZE_LABEL=""
MODEL_LICENSE_NOTE=""
MODEL_DOWNLOAD_URL=""
MODEL_EXPECTED_SHA256=""
BUILD_JOBS=0

LLM_BASE_URL=""
PARTNER_IP=""
RESOLVED_LLM_BASE_URL=""
DEFAULT_LLM_BASE_URL="http://ark-llm.local:8080"

INSTALL_OWNER=""
INSTALL_GROUP=""

OS=""
ARCH=""

APT_BASELINE_PACKAGES="ca-certificates curl git python3 python3-venv python3-pip python3-dev build-essential pkg-config rsync unzip jq"
LLAMA_APT_PACKAGES="cmake libcurl4-openssl-dev ccache"
APT_PACKAGES="$APT_BASELINE_PACKAGES"

usage() {
  cat <<'EOF'
Ark Pi install bootstrap

Bootstraps the Ark Pi app: clone/update repo, Python venv, pip install -e,
role-specific data directories, deployment template render, and optional
env/systemd file install.

Does not download GGUF models unless --download-model is passed.
Optional llama.cpp source build with --llama-build.
On Debian-family hosts, can install apt prerequisites (git, python3, build tools, etc.).
Llama build apt extras (cmake, libcurl4-openssl-dev, ccache) install only with --llama-build.

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
  --llama-build             Clone and build llama.cpp (role llm or both only)
  --no-llama-build          Explicitly skip llama.cpp build
  --llama-repo URL          llama.cpp git repository
  --llama-ref REF           llama.cpp git ref (default: master)
  --llama-dir PATH          llama.cpp source dir (default: $DATA_DIR/vendor/llama.cpp)
  --llama-build-dir PATH    llama.cpp cmake build dir (default: $LLAMA_DIR/build)
  --llama-bin PATH          llama-server binary path (default: $LLAMA_BUILD_DIR/bin/llama-server)
  --model-dir PATH          Model directory (default: $DATA_DIR/models)
  --model-path PATH         GGUF model path (default: $MODEL_DIR/model.gguf)
  --require-model           Treat missing model file as validation failure
  --download-model          Download a GGUF model during install (role llm or both)
  --model-preset NAME       Model preset: qwen3-4b-q4km, qwen3-8b-q4km, or custom
                            (default with --download-model: qwen3-4b-q4km)
  --model-repo REPO_ID      Hugging Face repo for --model-preset custom
  --model-file FILENAME     GGUF filename for --model-preset custom
  --model-revision REV      Hugging Face revision (default: main)
  --model-url URL           Custom download URL (overrides repo/file URL)
  --model-sha256 SHA256     Expected SHA256 for custom model or preset override
  --force-model-download    Replace existing model after successful verification
  --build-jobs N            Parallel cmake build jobs (default: CPU count or 2)
  --llm-base-url URL        Partner LLM base URL for ark-rag.env (role rag or both)
  --partner-ip HOST_OR_IP   Convenience alias: http://HOST:8080 (role rag or both)
  --help                    Show this help

Examples:
  sh install.sh --role rag --dry-run
  sh install.sh --role rag --install-services --llm-base-url http://10.255.255.101:8080 --yes
  sh install.sh --role rag --install-services --partner-ip 10.255.255.101 --yes
  sh install.sh --role llm --llama-build --dry-run
  sh install.sh --role llm --download-model --dry-run
  sh install.sh --role llm --install-services --llama-build --download-model --yes
  sh install.sh --role rag --no-os-packages --dry-run
  sh install.sh --role rag --install-services --dry-run
  sh install.sh --role rag --validate-only --prefix /path/to/prefix --data-dir /path/to/data --generated-dir /path/to/generated
  sh install.sh --role rag --prefix /path/to/prefix --data-dir /path/to/data --service-root /path/to/service-root --install-services --yes
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
      --llama-build)
        LLAMA_BUILD=1
        shift
        ;;
      --no-llama-build)
        NO_LLAMA_BUILD=1
        shift
        ;;
      --require-model)
        REQUIRE_MODEL=1
        shift
        ;;
      --download-model)
        DOWNLOAD_MODEL=1
        shift
        ;;
      --force-model-download)
        FORCE_MODEL_DOWNLOAD=1
        shift
        ;;
      --model-preset=*)
        MODEL_PRESET="${1#*=}"
        shift
        ;;
      --model-preset)
        if [ $# -lt 2 ]; then
          die "missing value for --model-preset"
        fi
        MODEL_PRESET="$2"
        shift 2
        ;;
      --model-repo=*)
        MODEL_REPO="${1#*=}"
        shift
        ;;
      --model-repo)
        if [ $# -lt 2 ]; then
          die "missing value for --model-repo"
        fi
        MODEL_REPO="$2"
        shift 2
        ;;
      --model-file=*)
        MODEL_FILE="${1#*=}"
        shift
        ;;
      --model-file)
        if [ $# -lt 2 ]; then
          die "missing value for --model-file"
        fi
        MODEL_FILE="$2"
        shift 2
        ;;
      --model-revision=*)
        MODEL_REVISION="${1#*=}"
        shift
        ;;
      --model-revision)
        if [ $# -lt 2 ]; then
          die "missing value for --model-revision"
        fi
        MODEL_REVISION="$2"
        shift 2
        ;;
      --model-url=*)
        MODEL_URL="${1#*=}"
        shift
        ;;
      --model-url)
        if [ $# -lt 2 ]; then
          die "missing value for --model-url"
        fi
        MODEL_URL="$2"
        shift 2
        ;;
      --model-sha256=*)
        MODEL_SHA256="${1#*=}"
        shift
        ;;
      --model-sha256)
        if [ $# -lt 2 ]; then
          die "missing value for --model-sha256"
        fi
        MODEL_SHA256="$2"
        shift 2
        ;;
      --llama-repo=*)
        LLAMA_REPO="${1#*=}"
        shift
        ;;
      --llama-repo)
        if [ $# -lt 2 ]; then
          die "missing value for --llama-repo"
        fi
        LLAMA_REPO="$2"
        shift 2
        ;;
      --llama-ref=*)
        LLAMA_REF="${1#*=}"
        shift
        ;;
      --llama-ref)
        if [ $# -lt 2 ]; then
          die "missing value for --llama-ref"
        fi
        LLAMA_REF="$2"
        shift 2
        ;;
      --llama-dir=*)
        LLAMA_DIR="${1#*=}"
        shift
        ;;
      --llama-dir)
        if [ $# -lt 2 ]; then
          die "missing value for --llama-dir"
        fi
        LLAMA_DIR="$2"
        shift 2
        ;;
      --llama-build-dir=*)
        LLAMA_BUILD_DIR="${1#*=}"
        shift
        ;;
      --llama-build-dir)
        if [ $# -lt 2 ]; then
          die "missing value for --llama-build-dir"
        fi
        LLAMA_BUILD_DIR="$2"
        shift 2
        ;;
      --llama-bin=*)
        LLAMA_BIN="${1#*=}"
        shift
        ;;
      --llama-bin)
        if [ $# -lt 2 ]; then
          die "missing value for --llama-bin"
        fi
        LLAMA_BIN="$2"
        shift 2
        ;;
      --model-dir=*)
        MODEL_DIR="${1#*=}"
        shift
        ;;
      --model-dir)
        if [ $# -lt 2 ]; then
          die "missing value for --model-dir"
        fi
        MODEL_DIR="$2"
        shift 2
        ;;
      --model-path=*)
        MODEL_PATH="${1#*=}"
        shift
        ;;
      --model-path)
        if [ $# -lt 2 ]; then
          die "missing value for --model-path"
        fi
        MODEL_PATH="$2"
        shift 2
        ;;
      --build-jobs=*)
        BUILD_JOBS="${1#*=}"
        shift
        ;;
      --build-jobs)
        if [ $# -lt 2 ]; then
          die "missing value for --build-jobs"
        fi
        BUILD_JOBS="$2"
        shift 2
        ;;
      --llm-base-url=*)
        LLM_BASE_URL="${1#*=}"
        shift
        ;;
      --llm-base-url)
        if [ $# -lt 2 ]; then
          die "missing value for --llm-base-url"
        fi
        LLM_BASE_URL="$2"
        shift 2
        ;;
      --partner-ip=*)
        PARTNER_IP="${1#*=}"
        shift
        ;;
      --partner-ip)
        if [ $# -lt 2 ]; then
          die "missing value for --partner-ip"
        fi
        PARTNER_IP="$2"
        shift 2
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

resolve_llama_paths() {
  if [ -z "$MODEL_DIR" ]; then
    MODEL_DIR="$DATA_DIR/models"
  fi
  if [ -z "$MODEL_PATH" ]; then
    MODEL_PATH="$MODEL_DIR/model.gguf"
  fi
  if [ -z "$LLAMA_DIR" ]; then
    LLAMA_DIR="$DATA_DIR/vendor/llama.cpp"
  fi
  if [ -z "$LLAMA_BUILD_DIR" ]; then
    LLAMA_BUILD_DIR="$LLAMA_DIR/build"
  fi
  if [ -z "$LLAMA_BIN" ]; then
    LLAMA_BIN="$LLAMA_BUILD_DIR/bin/llama-server"
  fi
}

should_build_llama() {
  if [ "$NO_LLAMA_BUILD" -eq 1 ]; then
    return 1
  fi
  if [ "$LLAMA_BUILD" -ne 1 ]; then
    return 1
  fi
  case "$ROLE" in
    llm|both) return 0 ;;
  esac
  return 1
}

should_include_llama_apt_packages() {
  should_build_llama
}

should_expect_llama_binary() {
  if should_build_llama; then
    return 0
  fi
  _dir=$(map_install_path "$LLAMA_DIR")
  if [ -d "$_dir/.git" ] || [ -f "$_dir/CMakeLists.txt" ]; then
    return 0
  fi
  return 1
}

validate_llama_flags() {
  if [ "$LLAMA_BUILD" -eq 1 ] && [ "$ROLE" = "rag" ]; then
    die "--llama-build requires role llm or both (not rag)"
  fi
  if [ "$LLAMA_BUILD" -eq 1 ] && [ "$NO_LLAMA_BUILD" -eq 1 ]; then
    die "cannot use --llama-build with --no-llama-build"
  fi
}

normalize_partner_ip() {
  _value="$1"
  case "$_value" in
    http://*|https://*)
      echo "$_value"
      ;;
    *)
      echo "http://${_value}:8080"
      ;;
  esac
}

resolve_llm_base_url() {
  RESOLVED_LLM_BASE_URL=""
  if [ -n "$LLM_BASE_URL" ]; then
    RESOLVED_LLM_BASE_URL="$LLM_BASE_URL"
  elif [ -n "$PARTNER_IP" ]; then
    RESOLVED_LLM_BASE_URL=$(normalize_partner_ip "$PARTNER_IP")
  fi
}

validate_llm_base_url_shape() {
  _url="$1"
  case "$_url" in
    http://*|https://*) ;;
    *)
      die "invalid LLM base URL: must start with http:// or https:// (got: $_url)"
      ;;
  esac
}

validate_llm_url_flags() {
  if [ "$ROLE" = "llm" ]; then
    if [ -n "$LLM_BASE_URL" ]; then
      die "--llm-base-url requires role rag or both (not llm)"
    fi
    if [ -n "$PARTNER_IP" ]; then
      die "--partner-ip requires role rag or both (not llm)"
    fi
    return 0
  fi
  if [ -n "$RESOLVED_LLM_BASE_URL" ]; then
    validate_llm_base_url_shape "$RESOLVED_LLM_BASE_URL"
  fi
}

display_llm_base_url() {
  if [ -n "$RESOLVED_LLM_BASE_URL" ]; then
    echo "$RESOLVED_LLM_BASE_URL"
  else
    echo "$DEFAULT_LLM_BASE_URL"
  fi
}

resolve_model_download_defaults() {
  if [ "$DOWNLOAD_MODEL" -eq 1 ] && [ -z "$MODEL_PRESET" ]; then
    MODEL_PRESET="qwen3-4b-q4km"
  fi
}

resolve_model_metadata() {
  resolve_model_download_defaults

  MODEL_PRESET_LABEL=""
  MODEL_SIZE_LABEL=""
  MODEL_LICENSE_NOTE=""
  MODEL_DOWNLOAD_URL=""
  _preset_sha=""

  case "$ROLE" in
    llm|both) ;;
    *) return 0 ;;
  esac

  if [ -z "$MODEL_PRESET" ] && [ "$DOWNLOAD_MODEL" -eq 0 ] \
    && [ -z "$MODEL_SHA256" ] && [ -z "$MODEL_URL" ] \
    && [ -z "$MODEL_REPO" ] && [ -z "$MODEL_FILE" ]; then
    return 0
  fi

  if [ -z "$MODEL_PRESET" ] && { [ -n "$MODEL_URL" ] || [ -n "$MODEL_REPO" ] \
    || [ -n "$MODEL_FILE" ]; }; then
    MODEL_PRESET="custom"
  fi

  case "$MODEL_PRESET" in
    qwen3-4b-q4km)
      MODEL_PRESET_LABEL="Qwen3 4B Q4_K_M"
      MODEL_REPO="Qwen/Qwen3-4B-GGUF"
      MODEL_FILE="Qwen3-4B-Q4_K_M.gguf"
      MODEL_REVISION="main"
      MODEL_SIZE_LABEL="2.5 GB"
      MODEL_LICENSE_NOTE="Apache-2.0 per Hugging Face model page"
      MODEL_DOWNLOAD_URL="https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
      _preset_sha="7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
      ;;
    qwen3-8b-q4km)
      MODEL_PRESET_LABEL="Qwen3 8B Q4_K_M"
      MODEL_REPO="Aldaris/Qwen3-8B-Q4_K_M-GGUF"
      MODEL_FILE="qwen3-8b-q4_k_m.gguf"
      MODEL_REVISION="main"
      MODEL_SIZE_LABEL="5.03 GB"
      MODEL_LICENSE_NOTE="Apache-2.0 per Hugging Face model page"
      MODEL_DOWNLOAD_URL="https://huggingface.co/Aldaris/Qwen3-8B-Q4_K_M-GGUF/resolve/main/qwen3-8b-q4_k_m.gguf"
      _preset_sha="609eb8a9fb256d0e2be8b8d252b00bae7c0496fac5e9ccca190206abbb24e2e5"
      ;;
    custom)
      MODEL_PRESET_LABEL="custom"
      if [ -n "$MODEL_URL" ]; then
        MODEL_DOWNLOAD_URL="$MODEL_URL"
      elif [ -n "$MODEL_REPO" ] && [ -n "$MODEL_FILE" ]; then
        MODEL_DOWNLOAD_URL="https://huggingface.co/$MODEL_REPO/resolve/$MODEL_REVISION/$MODEL_FILE"
      fi
      ;;
    "")
      if [ -n "$MODEL_SHA256" ]; then
        MODEL_EXPECTED_SHA256="$MODEL_SHA256"
      fi
      return 0
      ;;
    *)
      die "unknown model preset: $MODEL_PRESET (use qwen3-4b-q4km, qwen3-8b-q4km, or custom)"
      ;;
  esac

  if [ -n "$MODEL_SHA256" ]; then
    MODEL_EXPECTED_SHA256="$MODEL_SHA256"
  elif [ -n "$_preset_sha" ]; then
    MODEL_EXPECTED_SHA256="$_preset_sha"
  else
    MODEL_EXPECTED_SHA256=""
  fi
}

validate_download_model_flags() {
  if [ "$DOWNLOAD_MODEL" -eq 1 ] && [ "$ROLE" = "rag" ]; then
    die "--download-model requires role llm or both (not rag)"
  fi

  resolve_model_download_defaults

  if [ -n "$MODEL_PRESET" ]; then
    case "$MODEL_PRESET" in
      qwen3-4b-q4km|qwen3-8b-q4km|custom) ;;
      *)
        die "unknown model preset: $MODEL_PRESET (use qwen3-4b-q4km, qwen3-8b-q4km, or custom)"
        ;;
    esac
  fi

  if [ "$MODEL_PRESET" = "custom" ] || [ -n "$MODEL_URL" ] \
    || [ -n "$MODEL_REPO" ] || [ -n "$MODEL_FILE" ]; then
    if [ -z "$MODEL_SHA256" ]; then
      die "custom model requires --model-sha256"
    fi
    if [ "$DOWNLOAD_MODEL" -eq 1 ]; then
      if [ -z "$MODEL_URL" ]; then
        if [ -z "$MODEL_REPO" ] || [ -z "$MODEL_FILE" ]; then
          die "custom model requires --model-url or both --model-repo and --model-file"
        fi
      fi
    fi
  fi

  if [ "$DOWNLOAD_MODEL" -eq 1 ]; then
    resolve_model_metadata
    if [ -z "$MODEL_DOWNLOAD_URL" ]; then
      die "model download URL could not be resolved"
    fi
    if [ -z "$MODEL_EXPECTED_SHA256" ]; then
      die "model download requires a SHA256 checksum"
    fi
  fi
}

should_download_model() {
  if [ "$DOWNLOAD_MODEL" -ne 1 ]; then
    return 1
  fi
  if [ "$DRY_RUN" -eq 1 ] || [ "$VALIDATE_ONLY" -eq 1 ]; then
    return 1
  fi
  case "$ROLE" in
    llm|both) return 0 ;;
  esac
  return 1
}

should_verify_model_sha256() {
  [ -n "$MODEL_EXPECTED_SHA256" ]
}

should_have_model_metadata() {
  case "$ROLE" in
    llm|both) ;;
    *) return 1 ;;
  esac
  if [ "$DOWNLOAD_MODEL" -eq 1 ]; then
    return 0
  fi
  if [ -n "$MODEL_PRESET" ]; then
    return 0
  fi
  if [ -n "$MODEL_SHA256" ]; then
    return 0
  fi
  if [ -n "$MODEL_URL" ] || [ -n "$MODEL_REPO" ]; then
    return 0
  fi
  return 1
}

verify_model_sha256() {
  _file="$1"
  if ! command_exists sha256sum; then
    echo "install.sh: sha256sum not found" >&2
    return 1
  fi
  if [ -z "$MODEL_EXPECTED_SHA256" ]; then
    echo "install.sh: no expected SHA256 configured" >&2
    return 1
  fi
  _actual=$(sha256sum "$_file" | awk '{print $1}')
  _expected=$(printf '%s' "$MODEL_EXPECTED_SHA256" | tr '[:upper:]' '[:lower:]')
  _actual=$(printf '%s' "$_actual" | tr '[:upper:]' '[:lower:]')
  if [ "$_actual" != "$_expected" ]; then
    echo "install.sh: SHA256 mismatch" >&2
    echo "  expected: $_expected" >&2
    echo "  actual:   $_actual" >&2
    return 1
  fi
  return 0
}

existing_model_matches_expected_sha256() {
  if ! model_path_exists; then
    return 1
  fi
  if [ -z "$MODEL_EXPECTED_SHA256" ]; then
    return 0
  fi
  verify_model_sha256 "$(map_install_path "$MODEL_PATH")"
}

print_model_download_notice() {
  echo ""
  echo "Downloading GGUF model (internet required):"
  echo "  Preset:    ${MODEL_PRESET:-custom}"
  echo "  Label:     $MODEL_PRESET_LABEL"
  if [ -n "$MODEL_REPO" ]; then
    echo "  Repo:      $MODEL_REPO"
  fi
  if [ -n "$MODEL_FILE" ]; then
    echo "  File:      $MODEL_FILE"
  fi
  if [ -n "$MODEL_SIZE_LABEL" ]; then
    echo "  Size:      $MODEL_SIZE_LABEL"
  fi
  if [ -n "$MODEL_LICENSE_NOTE" ]; then
    echo "  License:   $MODEL_LICENSE_NOTE"
  fi
  echo "  Target:    $MODEL_PATH"
  echo "  SHA256:    $MODEL_EXPECTED_SHA256"
  echo "  URL:       $MODEL_DOWNLOAD_URL"
  echo "  Offline operation starts after the model is local."
}

download_model_gguf() {
  if ! should_download_model; then
    return 0
  fi

  _model_dir=$(map_install_path "$MODEL_DIR")
  _model_path=$(map_install_path "$MODEL_PATH")
  mkdir -p "$_model_dir"

  if existing_model_matches_expected_sha256; then
    echo ""
    echo "Model file already present and SHA256 matches; skipping download."
    echo "  $MODEL_PATH"
    return 0
  fi

  if model_path_exists; then
    if [ "$FORCE_MODEL_DOWNLOAD" -eq 0 ]; then
      die "model file exists at $MODEL_PATH but SHA256 does not match expected checksum (use --force-model-download to replace)"
    fi
    echo ""
    echo "Replacing existing model at $MODEL_PATH (--force-model-download)"
  fi

  print_model_download_notice

  _tmp="$_model_dir/model.gguf.tmp.$$"
  if ! curl -fL --retry 3 --retry-delay 5 --connect-timeout 30 -o "$_tmp" "$MODEL_DOWNLOAD_URL"; then
    rm -f "$_tmp"
    die "model download failed from $MODEL_DOWNLOAD_URL (Hugging Face/Xet redirected downloads may fail on poor networks)"
  fi

  if ! verify_model_sha256 "$_tmp"; then
    rm -f "$_tmp"
    die "downloaded model failed SHA256 verification"
  fi

  mv "$_tmp" "$_model_path"
  echo "Model installed at $MODEL_PATH"
}

apt_packages_list() {
  _list="$APT_BASELINE_PACKAGES"
  if should_include_llama_apt_packages; then
    _list="$_list $LLAMA_APT_PACKAGES"
  fi
  echo "$_list"
}

resolve_build_jobs() {
  if [ "$BUILD_JOBS" -gt 0 ] 2>/dev/null; then
    return 0
  fi
  if command_exists nproc; then
    BUILD_JOBS=$(nproc)
    return 0
  fi
  BUILD_JOBS=2
}

model_path_exists() {
  [ -f "$(map_install_path "$MODEL_PATH")" ]
}

llama_server_binary_exists() {
  _bin=$(map_install_path "$LLAMA_BIN")
  [ -x "$_bin" ]
}

should_start_llm_service() {
  model_path_exists && llama_server_binary_exists
}

print_llm_start_deferred_message() {
  echo ""
  if ! model_path_exists && ! llama_server_binary_exists; then
    echo "Skipping systemctl start for ark-llm.service (model file and llama-server binary missing)."
  elif ! model_path_exists; then
    echo "Skipping systemctl start for ark-llm.service (model file missing)."
  else
    echo "Skipping systemctl start for ark-llm.service (llama-server binary missing)."
  fi
  if ! model_path_exists; then
    echo "Place a GGUF at $MODEL_PATH, then run: sudo systemctl start ark-llm.service"
  fi
  if ! llama_server_binary_exists; then
    echo "Build llama.cpp with --llama-build or provide --llama-bin, then run: sudo systemctl start ark-llm.service"
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
  if [ "$_which" = "llama-dir-parent" ] && [ "${ARK_PI_INSTALL_TEST_UNWRITABLE_LLAMA_DIR_PARENT:-0}" = "1" ]; then
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

prepare_llama_dir_parent() {
  if ! should_build_llama; then
    return 0
  fi
  _parent=$(path_dirname "$LLAMA_DIR")
  prepare_install_owned_path "$_parent" "llama dir parent" "llama-dir-parent"
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
  if should_build_llama; then
    _print_install_path_ownership_plan "$(path_dirname "$LLAMA_DIR")" "llama dir parent" "llama-dir-parent"
  fi
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
  echo "Install these packages manually: $(apt_packages_list)" >&2
}

apt_install_command() {
  echo "apt-get install -y $(apt_packages_list)"
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
    echo "  Packages: $(apt_packages_list)"
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
  if ! run_as_root apt-get install -y $(apt_packages_list); then
    die "apt-get install failed"
  fi
}

# Test-only: map /etc paths into ARK_PI_INSTALL_TEST_SYSTEM_ROOT for offline tests.
map_service_env_path() {
  _path="$1"
  if [ -n "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT:-}" ]; then
    case "$_path" in
      /etc/*)
        echo "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT}${_path}"
        return 0
        ;;
    esac
  fi
  echo "$_path"
}

service_dest() {
  _suffix="$1"
  if [ "$SERVICE_ROOT" = "/" ]; then
    map_service_env_path "$_suffix"
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
  case "$ROLE" in
    llm|both)
      echo "Llama build:           $([ "$LLAMA_BUILD" -eq 1 ] && [ "$NO_LLAMA_BUILD" -eq 0 ] && echo yes || echo no)"
      echo "Llama dir:             $LLAMA_DIR"
      echo "Llama binary:          $LLAMA_BIN"
      echo "Model dir:             $MODEL_DIR"
      echo "Model path:            $MODEL_PATH"
      echo "Require model:         $([ "$REQUIRE_MODEL" -eq 1 ] && echo yes || echo no)"
      echo "Download model:        $([ "$DOWNLOAD_MODEL" -eq 1 ] && echo yes || echo no)"
      if [ "$DOWNLOAD_MODEL" -eq 1 ]; then
        echo "Model preset:          ${MODEL_PRESET:-qwen3-4b-q4km}"
        if [ -n "$MODEL_PRESET_LABEL" ]; then
          echo "Model label:           $MODEL_PRESET_LABEL"
        fi
        if [ -n "$MODEL_EXPECTED_SHA256" ]; then
          echo "Model SHA256:          $MODEL_EXPECTED_SHA256"
        fi
      fi
      ;;
  esac
  case "$ROLE" in
    rag|both)
      echo "Partner LLM URL:       $(display_llm_base_url)"
      ;;
    llm)
      echo "Partner LLM URL:       n/a"
      ;;
  esac
  echo ""
}

data_dirs_for_role() {
  case "$ROLE" in
    rag)
      echo "$DATA_DIR/data/workspace"
      echo "$DATA_DIR/data/sources"
      ;;
    llm)
      echo "$MODEL_DIR"
      ;;
    both)
      echo "$DATA_DIR/data/workspace"
      echo "$DATA_DIR/data/sources"
      echo "$MODEL_DIR"
      ;;
  esac
}

render_deploy_command() {
  _deploy_role=$(deploy_role_for_install_role)
  _cmd="$PREFIX/.venv/bin/ark deploy render --output-dir $GENERATED_DIR --role $_deploy_role --force"
  case "$ROLE" in
    llm|both)
      _cmd="$_cmd --prefix $PREFIX --llama-bin $LLAMA_BIN --model-dir $MODEL_DIR --model-path $MODEL_PATH"
      ;;
  esac
  case "$ROLE" in
    rag|both)
      if [ -n "$RESOLVED_LLM_BASE_URL" ]; then
        _cmd="$_cmd --llm-base-url $RESOLVED_LLM_BASE_URL"
      fi
      ;;
  esac
  echo "$_cmd"
}

print_llama_build_steps() {
  if ! should_build_llama; then
    return 0
  fi
  echo ""
  echo "llama.cpp build steps:"
  echo "  Clone or update llama.cpp at $LLAMA_DIR from $LLAMA_REPO (ref $LLAMA_REF)"
  echo "  Run cmake -S $LLAMA_DIR -B $LLAMA_BUILD_DIR -DCMAKE_BUILD_TYPE=Release"
  resolve_build_jobs
  echo "  Run cmake --build $LLAMA_BUILD_DIR --config Release -j $BUILD_JOBS"
  echo "  Verify $LLAMA_BIN exists and is executable"
}

print_model_download_steps() {
  case "$ROLE" in
    llm|both) ;;
    *) return 0 ;;
  esac
  echo ""
  if [ "$DOWNLOAD_MODEL" -eq 1 ]; then
    echo "Model download steps:"
    echo "  Preset:    ${MODEL_PRESET:-qwen3-4b-q4km}"
    if [ -n "$MODEL_PRESET_LABEL" ]; then
      echo "  Label:     $MODEL_PRESET_LABEL"
    fi
    if [ -n "$MODEL_REPO" ]; then
      echo "  Repo:      $MODEL_REPO"
    fi
    if [ -n "$MODEL_FILE" ]; then
      echo "  File:      $MODEL_FILE"
    fi
    if [ -n "$MODEL_SIZE_LABEL" ]; then
      echo "  Size:      $MODEL_SIZE_LABEL"
    fi
    if [ -n "$MODEL_LICENSE_NOTE" ]; then
      echo "  License:   $MODEL_LICENSE_NOTE"
    fi
    echo "  Target:    $MODEL_PATH"
    if [ -n "$MODEL_EXPECTED_SHA256" ]; then
      echo "  SHA256:    $MODEL_EXPECTED_SHA256"
    fi
    if [ -n "$MODEL_DOWNLOAD_URL" ]; then
      echo "  URL:       $MODEL_DOWNLOAD_URL"
    fi
    if [ "$MODEL_PRESET" = "qwen3-8b-q4km" ]; then
      echo "  Note:      advanced preset; may be tight on Raspberry Pi 5 8GB"
    fi
    echo "  Internet is required for download; offline operation starts after model is local."
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  Dry run: no download will occur."
    fi
  else
    echo "Model placement: manual (copy a compatible GGUF to $MODEL_PATH or use --download-model)"
  fi
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
  print_llama_build_steps
  print_model_download_steps
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
        if [ "$_unit" = "ark-llm.service" ] && ! should_start_llm_service; then
          if ! model_path_exists; then
            echo "  Skip systemctl start $_unit (model file missing at $MODEL_PATH)"
            echo "  Place a GGUF at $MODEL_PATH, then run: sudo systemctl start ark-llm.service"
          elif ! llama_server_binary_exists; then
            echo "  Skip systemctl start $_unit (llama-server binary missing at $LLAMA_BIN)"
            echo "  Build llama.cpp with --llama-build or provide --llama-bin, then run: sudo systemctl start ark-llm.service"
          fi
        else
          echo "  systemctl start $_unit"
        fi
      done
    fi
  else
    echo "  Skip systemctl (service root is not /)"
  fi
}

print_future_service_steps() {
  echo ""
  echo "Not automated by install.sh:"
  if ! should_build_llama; then
    case "$ROLE" in
      llm|both)
        echo "  - Build llama.cpp (use --llama-build to opt in)"
        ;;
    esac
  fi
  if [ "$DOWNLOAD_MODEL" -eq 0 ]; then
    echo "  - Download or place GGUF model files"
  fi
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
  if should_download_model || should_verify_model_sha256; then
    if ! command_exists sha256sum; then
      die "sha256sum not found (required for model download/verification)"
    fi
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
      _msg="prefix git checkout at $PREFIX has local changes; inspect $_pref and commit or stash before re-running install.sh"
      if [ -d "$_pref/vendor" ]; then
        _msg="$_msg If vendor/ is a stale llama.cpp clone from an earlier install (old default under $PREFIX), inspect it and remove manually (e.g. rm -rf $PREFIX/vendor)."
      fi
      die "$_msg"
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
    echo "  OS packages:    install via apt ($(apt_packages_list))"
  else
    echo "  OS packages:    skip (check only)"
  fi
  if should_build_llama; then
    echo "  Llama build:    yes ($LLAMA_DIR -> $LLAMA_BIN)"
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

git_worktree_is_dirty() {
  _path="$1"
  [ -n "$(git -C "$_path" status --porcelain 2>/dev/null)" ]
}

git_fast_forward_branch() {
  _path="$1"
  _branch="$2"
  _label="$3"
  _display_path="$4"
  if git_worktree_is_dirty "$_path"; then
    die "$_label checkout at $_display_path has local modifications; inspect $_path and commit or stash before re-running install.sh"
  fi
  git -C "$_path" fetch origin "$_branch"
  git -C "$_path" checkout "$_branch"
  if ! git -C "$_path" merge --ff-only "origin/$_branch"; then
    die "$_label checkout at $_display_path cannot fast-forward to origin/$_branch; inspect $_path (local commits or diverged history)"
  fi
  echo "Updated $_label checkout at $_display_path to origin/$_branch"
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
    git_fast_forward_branch "$_pref" "$BRANCH" "Ark Pi" "$PREFIX"
    return 0
  fi
  git clone --branch "$BRANCH" "$REPO" "$_pref"
}

clone_or_update_llama_repo() {
  _dir=$(map_install_path "$LLAMA_DIR")
  if [ ! -d "$_dir" ]; then
    _parent=$(path_dirname "$_dir")
    mkdir -p "$_parent"
    git clone "$LLAMA_REPO" "$_dir"
  fi
  if [ -d "$_dir/.git" ]; then
    if git_worktree_is_dirty "$_dir"; then
      die "llama.cpp checkout at $LLAMA_DIR has local modifications; inspect $_dir and commit or stash before re-running install.sh"
    fi
    git -C "$_dir" fetch origin "$LLAMA_REF" 2>/dev/null || git -C "$_dir" fetch origin 2>/dev/null || true
    if git -C "$_dir" show-ref --verify --quiet "refs/remotes/origin/$LLAMA_REF" 2>/dev/null; then
      git -C "$_dir" checkout "$LLAMA_REF"
      if ! git -C "$_dir" merge --ff-only "origin/$LLAMA_REF"; then
        die "llama.cpp checkout at $LLAMA_DIR cannot fast-forward to origin/$LLAMA_REF; inspect $_dir (local commits or diverged history)"
      fi
      echo "Updated llama.cpp checkout at $LLAMA_DIR to origin/$LLAMA_REF"
    else
      git -C "$_dir" checkout "$LLAMA_REF"
    fi
    return 0
  fi
  die "llama.cpp path exists but is not a git checkout: $LLAMA_DIR"
}

build_llama_cpp() {
  if ! should_build_llama; then
    return 0
  fi
  if ! command_exists cmake; then
    die "cmake not found (required for --llama-build)"
  fi
  clone_or_update_llama_repo
  _llama_dir=$(map_install_path "$LLAMA_DIR")
  _build_dir=$(map_install_path "$LLAMA_BUILD_DIR")
  _bin=$(map_install_path "$LLAMA_BIN")
  if ! cmake -S "$_llama_dir" -B "$_build_dir" -DCMAKE_BUILD_TYPE=Release; then
    die "cmake configure failed for llama.cpp"
  fi
  resolve_build_jobs
  if ! cmake --build "$_build_dir" --config Release -j "$BUILD_JOBS"; then
    die "cmake build failed for llama.cpp"
  fi
  if [ ! -x "$_bin" ]; then
    die "llama-server binary missing or not executable: $LLAMA_BIN"
  fi
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
  set -- "$_ark" deploy render --output-dir "$_generated" --role "$_deploy_role" --force
  case "$ROLE" in
    llm|both)
      set -- "$@" --prefix "$PREFIX" --llama-bin "$LLAMA_BIN" --model-dir "$MODEL_DIR" --model-path "$MODEL_PATH"
      ;;
  esac
  case "$ROLE" in
    rag|both)
      if [ -n "$RESOLVED_LLM_BASE_URL" ]; then
        set -- "$@" --llm-base-url "$RESOLVED_LLM_BASE_URL"
      fi
      ;;
  esac
  if ! "$@"; then
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
      if [ "$_unit" = "ark-llm.service" ] && ! should_start_llm_service; then
        print_llm_start_deferred_message
        continue
      fi
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

validation_env_logical_service_path() {
  _role="$1"
  case "$_role" in
    rag) echo /etc/ark-pi/ark-rag.env ;;
    llm) echo /etc/ark-pi/ark-llm.env ;;
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
    if [ "$SERVICE_ROOT" = "/" ]; then
      validation_env_logical_service_path "$_role"
      return 0
    fi
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

validation_env_read_path() {
  map_service_env_path "$1"
}

should_use_sudo_for_env_read() {
  _path="$1"
  if [ "$SERVICE_ROOT" != "/" ]; then
    return 1
  fi
  case "$_path" in
    /etc/ark-pi/*.env)
      return 0
      ;;
  esac
  if [ -n "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT:-}" ]; then
    case "$_path" in
      "${ARK_PI_INSTALL_TEST_SYSTEM_ROOT}"/etc/ark-pi/*.env)
        return 0
        ;;
    esac
  fi
  return 1
}

read_role_env_content() {
  _path="$1"
  _read_path=$(validation_env_read_path "$_path")
  if [ -r "$_read_path" ]; then
    cat "$_read_path"
    return 0
  fi
  if should_use_sudo_for_env_read "$_path"; then
    if command_exists sudo; then
      sudo cat "$_read_path"
      return $?
    fi
    return 1
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
    ARK_LLAMA_BIN) ARK_LLAMA_BIN="$_value"; export ARK_LLAMA_BIN ;;
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
  _display="${3:-$_path}"
  _unknown=""
  _unknown_sep=""
  _source=""
  _cleanup=0

  _read_path=$(validation_env_read_path "$_path")
  if [ -r "$_read_path" ]; then
    _source="$_read_path"
  elif should_use_sudo_for_env_read "$_path"; then
    if ! command_exists sudo; then
      record_validation_check role_env_read fail "cannot read $_display (sudo unavailable)"
      return 1
    fi
    _source=$(mktemp) || {
      record_validation_check role_env_read fail "cannot read $_display"
      return 1
    }
    _cleanup=1
    if ! sudo cat "$_read_path" >"$_source" 2>/dev/null; then
      rm -f "$_source"
      record_validation_check role_env_read fail "cannot read $_display"
      return 1
    fi
  else
    record_validation_check role_env_read fail "cannot read $_display"
    return 1
  fi

  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      ''|'#'*) continue ;;
    esac
    case "$_line" in
      *=*) ;;
      *)
        if [ "$_cleanup" -eq 1 ]; then
          rm -f "$_source"
        fi
        record_validation_check role_env_parse fail "malformed line in $_display: $_line"
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
  done < "$_source"

  if [ "$_cleanup" -eq 1 ]; then
    rm -f "$_source"
  fi

  if [ -n "$_unknown" ]; then
    record_validation_check role_env_unknown_keys warning "unknown keys in $_display (ignored): $_unknown"
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
  if ! load_role_env_for_validation "$_env_file" "$_role" "$_display"; then
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
  elif [ "$NO_START" -eq 1 ] && [ "$_unit" = "ark-llm.service" ]; then
    record_validation_check systemctl_active pass "$_unit is not active (--no-start; expected)"
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
      _model_dir=$(map_install_path "$MODEL_DIR")
      if [ -d "$_model_dir" ]; then
        record_validation_check model_dir pass "model dir exists: $MODEL_DIR"
      else
        record_validation_check model_dir fail "model dir missing: $MODEL_DIR"
      fi
      if should_build_llama || [ -d "$(map_install_path "$LLAMA_DIR")" ]; then
        _llama_dir=$(map_install_path "$LLAMA_DIR")
        if [ -d "$_llama_dir" ]; then
          record_validation_check llama_dir pass "llama.cpp source dir exists: $LLAMA_DIR"
        else
          record_validation_check llama_dir warning "llama.cpp source dir missing: $LLAMA_DIR"
        fi
      fi
      _bin=$(map_install_path "$LLAMA_BIN")
      if [ -x "$_bin" ]; then
        record_validation_check llama_server_binary pass "llama-server binary exists: $LLAMA_BIN"
        if "$_bin" --help >/dev/null 2>&1; then
          record_validation_check llama_server_help pass "llama-server --help succeeded"
        else
          record_validation_check llama_server_help fail "llama-server --help failed: $LLAMA_BIN"
        fi
      elif should_expect_llama_binary; then
        record_validation_check llama_server_binary fail "llama-server binary missing or not executable: $LLAMA_BIN"
      else
        record_validation_check llama_server_binary warning "llama-server binary not present: $LLAMA_BIN (optional until --llama-build)"
      fi
      _model=$(map_install_path "$MODEL_PATH")
      if [ -f "$_model" ]; then
        record_validation_check model_file pass "model file exists: $MODEL_PATH"
      elif [ "$REQUIRE_MODEL" -eq 1 ]; then
        record_validation_check model_file fail "model file missing: $MODEL_PATH (--require-model)"
      else
        record_validation_check model_file warning "model file missing: $MODEL_PATH (manual step)"
      fi
      if [ -n "$MODEL_PRESET" ] || [ "$DOWNLOAD_MODEL" -eq 1 ]; then
        if [ -n "$MODEL_DOWNLOAD_URL" ] && [ -n "$MODEL_EXPECTED_SHA256" ]; then
          record_validation_check model_preset pass "model preset resolved: ${MODEL_PRESET:-custom}"
        elif [ "$MODEL_PRESET" = "custom" ] && [ -n "$MODEL_EXPECTED_SHA256" ]; then
          record_validation_check model_preset pass "custom model metadata resolved"
        else
          record_validation_check model_preset fail "model preset metadata incomplete"
        fi
      fi
      if should_verify_model_sha256; then
        if [ -f "$_model" ]; then
          if verify_model_sha256 "$_model"; then
            record_validation_check model_sha256 pass "model SHA256 matches expected checksum"
          else
            record_validation_check model_sha256 fail "model SHA256 does not match expected checksum"
          fi
        elif [ "$REQUIRE_MODEL" -eq 1 ]; then
          record_validation_check model_sha256 warning "model file missing; SHA256 check skipped"
        else
          record_validation_check model_sha256 warning "model file missing; SHA256 check skipped"
        fi
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
      echo "  Check model dir, llama-server binary (when expected), model file, and role-env-aware ark preflight"
      echo "  Missing model file is a warning unless --require-model"
      if should_have_model_metadata; then
        echo "  Verify model SHA256 when preset or --model-sha256 is configured"
      fi
      ;;
  esac
  if should_build_llama; then
    echo "  Validate-only does not clone, fetch, build llama.cpp, or install apt packages"
  fi
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
  echo "  Does not download models or configure networking"
  echo "  Verify role env file is readable before ark commands (role_env_read; sudo cat for /etc/ark-pi/*.env when service root is /)"
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

should_print_sudo_env_load() {
  _env_file="$1"
  if [ "$INSTALL_SERVICES" -eq 0 ]; then
    return 1
  fi
  if [ "$SERVICE_ROOT" != "/" ]; then
    return 1
  fi
  case "$_env_file" in
    /etc/ark-pi/*.env)
      return 0
      ;;
  esac
  return 1
}

print_sudo_env_ark_command() {
  _env_file="$1"
  _ark_cmd="$2"
  echo "  sudo sh -c 'set -a; . $_env_file; set +a; exec $_ark_cmd'"
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
  if should_print_sudo_env_load "$_env_file"; then
    echo "  Installed service env files are root:root mode 0640."
    print_sudo_env_ark_command "$_env_file" "$_ark preflight"
    case "$_role" in
      rag) print_sudo_env_ark_command "$_env_file" "$_ark llm status" ;;
    esac
    return 0
  fi
  print_env_load_block "$_env_file"
  echo "  $_ark preflight"
  case "$_role" in
    rag) echo "  $_ark llm status" ;;
  esac
}

print_role_one_liner_example() {
  _role="$1"
  _ark="$2"
  _env_file=$(validation_env_display_path "$_role")
  echo "One-liner example ($_role):"
  if should_print_sudo_env_load "$_env_file"; then
    print_sudo_env_ark_command "$_env_file" "$_ark preflight"
  else
    echo "  set -a; . $_env_file; set +a; $_ark preflight"
  fi
}

print_rag_api_validation_commands() {
  _ark="$1"
  _deploy_role="$2"
  echo ""
  echo "RAG API checks:"
  echo "  $_ark llm test --llm-backend mock"
  echo "  $_ark deploy preflight --generated-dir $GENERATED_DIR --role $_deploy_role"
  echo "  $_ark deploy plan --generated-dir $GENERATED_DIR --role $_deploy_role"
  echo "  curl http://127.0.0.1:8000/healthz"
  echo "  curl http://127.0.0.1:8000/api/status"
}

print_llm_service_validation_commands() {
  echo ""
  echo "LLM service checks:"
  if [ "$INSTALL_SERVICES" -eq 1 ] && [ "$SERVICE_ROOT" = "/" ]; then
    echo "  sudo systemctl status ark-llm.service --no-pager"
  else
    echo "  systemctl status ark-llm.service --no-pager"
  fi
  echo "  ls -l $LLAMA_BIN"
  echo "  ls -l $MODEL_PATH"
  if ! model_path_exists; then
    echo "  Place a GGUF at $MODEL_PATH before: sudo systemctl start ark-llm.service"
  fi
  if [ -x "$(map_install_path "$LLAMA_BIN")" ]; then
    echo "  $LLAMA_BIN --help"
  fi
}

print_validation_commands() {
  _deploy_role=$(deploy_role_for_install_role)
  _ark="$PREFIX/.venv/bin/ark"
  echo ""
  echo "Validation commands (load role env first; bare ark preflight uses default config, not the service):"
  case "$ROLE" in
    rag)
      print_role_validation_commands rag "$_ark"
      print_role_one_liner_example rag "$_ark"
      print_rag_api_validation_commands "$_ark" "$_deploy_role"
      ;;
    llm)
      print_role_validation_commands llm "$_ark"
      print_role_one_liner_example llm "$_ark"
      echo ""
      echo "  $_ark deploy preflight --generated-dir $GENERATED_DIR --role $_deploy_role"
      print_llm_service_validation_commands
      ;;
    both)
      print_role_validation_commands rag "$_ark"
      echo ""
      print_role_validation_commands llm "$_ark"
      print_role_one_liner_example rag "$_ark"
      echo ""
      print_role_one_liner_example llm "$_ark"
      print_rag_api_validation_commands "$_ark" "$_deploy_role"
      print_llm_service_validation_commands
      ;;
  esac
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
  echo "Model placement remains manual; use --llama-build for optional llama.cpp source build."
  echo "Network setup remains manual."
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
  prepare_llama_dir_parent
  check_path_writable "$(map_install_path "$GENERATED_DIR")" "generated dir"
  ensure_clean_prefix
  clone_or_update_repo
  create_venv_and_install
  build_llama_cpp
  create_data_dirs
  download_model_gguf
  run_deploy_render
  install_service_files
  if [ "$INSTALL_SERVICES" -eq 1 ]; then
    case "$ROLE" in
      llm|both)
        if [ "$REQUIRE_MODEL" -eq 1 ] && ! model_path_exists; then
          die "model file required at $MODEL_PATH (--require-model)"
        fi
        ;;
    esac
  fi
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
  resolve_llama_paths
  detect_platform
  if [ -z "$ROLE" ]; then
    if is_interactive; then
      prompt_role
    else
      die "--role is required in non-interactive mode (use --role rag|llm|both)"
    fi
  fi
  validate_role
  resolve_llm_base_url
  validate_llm_url_flags
  validate_llama_flags
  validate_download_model_flags
  resolve_llama_paths
  resolve_model_metadata
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
