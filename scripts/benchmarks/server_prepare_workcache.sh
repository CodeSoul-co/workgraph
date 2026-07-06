#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEFAULT_ARCHIVE="$ROOT_DIR/workcache_server_data_20260706.tar.gz"
ARCHIVE_INPUT="${1:-$DEFAULT_ARCHIVE}"
HYPHA_DIR="${HYPHA_DIR:-$ROOT_DIR/hypha}"
HYPHA_URL="${HYPHA_URL:-https://github.com/CodeSoul-co/Hypha.git}"
HYPHA_BRANCH="${HYPHA_BRANCH:-cache-base}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"

resolve_archive() {
  local input="$1"
  if [[ -f "$input" ]]; then
    cd "$(dirname "$input")"
    printf '%s/%s\n' "$(pwd)" "$(basename "$input")"
    return 0
  fi

  if [[ "$input" != /* && -f "$ROOT_DIR/$input" ]]; then
    printf '%s/%s\n' "$ROOT_DIR" "$input"
    return 0
  fi

  return 1
}

check_commands() {
  local missing=()
  local cmd

  for cmd in git tar python3 node npm uv pdftotext rg; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done

  if ((${#missing[@]})); then
    echo "Missing required commands: ${missing[*]}" >&2
    echo "Install them first, then rerun this script." >&2
    exit 1
  fi
}

check_node_version() {
  local major
  major="$(node -p "Number(process.versions.node.split('.')[0])")"
  if [[ "$major" -lt 18 ]]; then
    echo "Node.js >=18 is required by Hypha; found $(node --version)." >&2
    echo "On AutoDL/conda hosts, one option is: conda install -y -c conda-forge nodejs=20" >&2
    exit 1
  fi
}

restore_data() {
  local archive
  if ! archive="$(resolve_archive "$ARCHIVE_INPUT")"; then
    echo "Data archive not found: $ARCHIVE_INPUT" >&2
    echo "Copy workcache_server_data_20260706.tar.gz to the repo root, or pass its path as the first argument." >&2
    exit 1
  fi

  echo "Restoring benchmark data from $archive"
  tar -xzf "$archive" -C "$ROOT_DIR"
}

prepare_hypha() {
  if [[ -e "$HYPHA_DIR" && ! -d "$HYPHA_DIR/.git" ]]; then
    echo "Hypha path exists but is not a git checkout: $HYPHA_DIR" >&2
    echo "Move it aside or set HYPHA_DIR=/path/to/Hypha before rerunning." >&2
    exit 1
  fi

  if [[ ! -d "$HYPHA_DIR/.git" ]]; then
    echo "Cloning Hypha into $HYPHA_DIR"
    git clone "$HYPHA_URL" "$HYPHA_DIR"
  fi

  echo "Updating Hypha $HYPHA_BRANCH"
  git -C "$HYPHA_DIR" fetch origin
  git -C "$HYPHA_DIR" checkout "$HYPHA_BRANCH"
  git -C "$HYPHA_DIR" pull --ff-only origin "$HYPHA_BRANCH"
  git -C "$HYPHA_DIR" log --oneline -1
}

build_hypha_workcache() {
  echo "Building Hypha WorkCache package"
  cd "$HYPHA_DIR"

  if [[ "${SKIP_HYPHA_NPM_CI:-0}" != "1" ]]; then
    echo "Installing Hypha npm dependencies from $NPM_REGISTRY"
    npm ci \
      --registry="$NPM_REGISTRY" \
      --prefer-online \
      --no-audit \
      --no-fund \
      --progress=false \
      --fetch-retries=5 \
      --fetch-retry-mintimeout=20000 \
      --fetch-retry-maxtimeout=120000
  else
    echo "Skipping Hypha npm dependency install because SKIP_HYPHA_NPM_CI=1"
  fi

  npm run build --workspace @hypha/workcache

  if [[ ! -f "$HYPHA_DIR/packages/workcache/dist/index.js" ]]; then
    echo "Hypha WorkCache build did not create packages/workcache/dist/index.js" >&2
    exit 1
  fi
}

prepare_tools() {
  echo "Preparing benchmark repositories and tools"
  "$ROOT_DIR/scripts/benchmarks/bootstrap.sh" clone
  "$ROOT_DIR/scripts/benchmarks/bootstrap.sh" env-tau2
  "$ROOT_DIR/scripts/benchmarks/setup_benchmark_tools.sh" tau2
  "$ROOT_DIR/scripts/benchmarks/setup_benchmark_tools.sh" financebench
  "$ROOT_DIR/scripts/benchmarks/setup_benchmark_tools.sh" tabmwp
  "$ROOT_DIR/scripts/benchmarks/check_benchmarks.py"
}

prepare_env() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    echo "Using existing $ROOT_DIR/.env"
    return 0
  fi

  if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
    echo "Creating $ROOT_DIR/.env from current environment"
    {
      printf 'WORKGRAPH_MODEL=%s\n' "${WORKGRAPH_MODEL:-deepseek-v4-pro}"
      printf 'DEEPSEEK_BASE_URL=%s\n' "${DEEPSEEK_BASE_URL:-https://api.deepseek.com/v1}"
      printf 'DEEPSEEK_API_KEY=%s\n' "$DEEPSEEK_API_KEY"
    } >"$ROOT_DIR/.env"
    chmod 600 "$ROOT_DIR/.env"
    return 0
  fi

  cat >"$ROOT_DIR/.env.server.template" <<'EOF'
WORKGRAPH_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=replace_with_server_key
EOF

  echo "Created $ROOT_DIR/.env.server.template" >&2
  echo "Create $ROOT_DIR/.env or rerun with DEEPSEEK_API_KEY=... before starting the benchmark." >&2
}

check_commands
check_node_version
restore_data
prepare_hypha
build_hypha_workcache
prepare_tools
prepare_env

echo "Server preparation complete."
echo "Start command:"
echo "  bash scripts/benchmarks/server_start_workcache_50x2.sh --background"
