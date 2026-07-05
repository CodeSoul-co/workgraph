#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOLS_DIR="$ROOT_DIR/external/tools"
TAU2_DIR="$ROOT_DIR/external/benchmarks/tau2-bench"

setup_tau2_tools() {
  cd "$TAU2_DIR"
  uv sync --extra dev --extra knowledge --extra gym

  if ! command -v srt >/dev/null 2>&1; then
    npm install -g @anthropic-ai/sandbox-runtime@0.0.23
  fi

  if ! command -v rg >/dev/null 2>&1; then
    echo "ripgrep (rg) is required for tau2 sandbox shell tools." >&2
    echo "Install it with Homebrew on macOS: brew install ripgrep" >&2
    return 1
  fi
}

setup_financebench_tools() {
  local dir="$TOOLS_DIR/financebench-tools"
  mkdir -p "$dir"
  cd "$dir"
  uv venv --python 3.12 .venv
  uv pip install -p .venv/bin/python \
    pypdf pdfplumber pandas numpy scikit-learn rank-bm25 rapidfuzz
}

setup_tabmwp_tools() {
  local dir="$TOOLS_DIR/tabmwp-tools"
  mkdir -p "$dir"
  cd "$dir"
  uv venv --python 3.12 .venv
  uv pip install -p .venv/bin/python pandas numpy sympy rapidfuzz
}

setup_browsergym_agentlab_tools() {
  local dir="$TOOLS_DIR/browsergym-agentlab"
  mkdir -p "$dir"
  cd "$dir"
  uv venv --python 3.12 .venv
  uv pip install -p .venv/bin/python browsergym browsergym-webarena agentlab
  .venv/bin/playwright install chromium

  mkdir -p "$dir/nltk_data"
  NLTK_DATA="$dir/nltk_data" .venv/bin/python - <<'PY'
import nltk
for package in ("punkt", "punkt_tab"):
    nltk.download(package, download_dir="nltk_data")
PY
}

case "${1:-all}" in
  tau2)
    setup_tau2_tools
    ;;
  financebench)
    setup_financebench_tools
    ;;
  tabmwp)
    setup_tabmwp_tools
    ;;
  browsergym)
    setup_browsergym_agentlab_tools
    ;;
  all)
    setup_tau2_tools
    setup_financebench_tools
    setup_tabmwp_tools
    setup_browsergym_agentlab_tools
    ;;
  *)
    echo "Usage: $0 {all|tau2|financebench|tabmwp|browsergym}" >&2
    exit 2
    ;;
esac
