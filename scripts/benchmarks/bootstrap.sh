#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXTERNAL_DIR="$ROOT_DIR/external/benchmarks"
FINANCE_DIR="$ROOT_DIR/data/raw/benchmarks/financebench"

TAU2_URL="https://github.com/sierra-research/tau2-bench.git"
TAU2_COMMIT="1901a301961cbbe3fd11f3e84a2a376530c759e3"
WEBARENA_URL="https://github.com/web-arena-x/webarena.git"
WEBARENA_COMMIT="dce04686a56253aefba7b18a4fa0937cf1dc987b"
PROMPTPG_URL="https://github.com/lupantech/PromptPG.git"
PROMPTPG_COMMIT="5a1a52214521590b075f545b76a4f5ce666345e3"
FINANCE_JSONL_URL="https://huggingface.co/datasets/PatronusAI/financebench/resolve/main/financebench_merged.jsonl"

clone_repo() {
  local url="$1"
  local path="$2"
  local expected="$3"

  if [[ ! -d "$path/.git" ]]; then
    git clone --depth 1 "$url" "$path"
  fi

  local actual
  actual="$(git -C "$path" rev-parse HEAD)"
  if [[ "$actual" != "$expected" ]]; then
    echo "warning: $path is at $actual, expected $expected" >&2
  fi
}

clone_all() {
  mkdir -p "$EXTERNAL_DIR"
  clone_repo "$TAU2_URL" "$EXTERNAL_DIR/tau2-bench" "$TAU2_COMMIT"
  clone_repo "$WEBARENA_URL" "$EXTERNAL_DIR/webarena" "$WEBARENA_COMMIT"
  clone_repo "$PROMPTPG_URL" "$EXTERNAL_DIR/PromptPG" "$PROMPTPG_COMMIT"
}

download_financebench() {
  mkdir -p "$FINANCE_DIR"
  curl -L --fail --retry 3 -o "$FINANCE_DIR/financebench_merged.jsonl" "$FINANCE_JSONL_URL"
  "$ROOT_DIR/scripts/benchmarks/download_financebench_pdfs.py"
}

env_tau2() {
  cd "$EXTERNAL_DIR/tau2-bench"
  uv sync --extra dev
}

env_webarena() {
  cd "$EXTERNAL_DIR/webarena"
  uv venv --python 3.10 .venv
  uv pip install -p .venv/bin/python -r requirements.txt -e .
  .venv/bin/playwright install chromium
}

env_promptpg() {
  cd "$EXTERNAL_DIR/PromptPG"
  uv venv --python 3.8 .venv
  uv pip install -p .venv/bin/python pip setuptools wheel
  .venv/bin/python -m pip install --use-deprecated=legacy-resolver -r requirements.txt
}

case "${1:-all}" in
  clone)
    clone_all
    ;;
  financebench)
    download_financebench
    ;;
  env-tau2)
    env_tau2
    ;;
  env-webarena)
    env_webarena
    ;;
  env-promptpg)
    env_promptpg
    ;;
  all)
    clone_all
    download_financebench
    env_tau2
    ;;
  *)
    echo "Usage: $0 {all|clone|financebench|env-tau2|env-webarena|env-promptpg}" >&2
    exit 2
    ;;
esac
