#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ALL_BENCHMARKS="tau2-bench,financebench,promptpg-tabmwp"
EXP_ID="${WORKCACHE_EXP_ID:-}"
SAMPLE_LIMIT="${WORKCACHE_SAMPLE_LIMIT:-${WORKCACHE_LIMIT:-50}}"
BENCHMARKS="${WORKCACHE_BENCHMARKS:-$ALL_BENCHMARKS}"
METHOD_SUITE="${WORKCACHE_METHOD_SUITE:-all}"
REPEAT_PASSES="${WORKCACHE_REPEAT_PASSES:-2}"
BACKGROUND=0
RESUME=0

usage() {
  cat <<'EOF'
Usage: scripts/benchmarks/server_start_workcache_50x2.sh [--background] [--resume]
       scripts/benchmarks/server_start_workcache_50x2.sh [--table table1|table2|table3|all]
       scripts/benchmarks/server_start_workcache_50x2.sh [--method-suite SUITE]
       scripts/benchmarks/server_start_workcache_50x2.sh [--sample-limit N|all]
       scripts/benchmarks/server_start_workcache_50x2.sh [--benchmark NAME]
       scripts/benchmarks/server_start_workcache_50x2.sh [--benchmarks LIST|all]

Table experiment suites:
  table1/main, table2/ablation, table3/mechanism, all

Benchmark names:
  tau2-bench, financebench, promptpg-tabmwp

Environment overrides:
  WORKCACHE_EXP_ID          default: real_hypha_all_50x2_server or real_hypha_<suite>_50x2_server
  WORKCACHE_METHOD_SUITE    default: all; accepts table1/table2/table3/all
  WORKCACHE_SAMPLE_LIMIT    default: 50; accepts a positive integer or all
  WORKCACHE_LIMIT           legacy alias used only when WORKCACHE_SAMPLE_LIMIT is unset
  WORKCACHE_BENCHMARKS      default: tau2-bench,financebench,promptpg-tabmwp
  WORKCACHE_REPEAT_PASSES   default: 2
EOF
}

while (($#)); do
  case "$1" in
    --background)
      BACKGROUND=1
      ;;
    --foreground)
      BACKGROUND=0
      ;;
    --resume)
      RESUME=1
      ;;
    --table|--method-suite)
      if [[ $# -lt 2 ]]; then
        echo "$1 requires table1, table2, table3, or all" >&2
        exit 2
      fi
      METHOD_SUITE="$2"
      shift
      ;;
    --sample-limit|--limit)
      if [[ $# -lt 2 ]]; then
        echo "$1 requires a value: positive integer or all" >&2
        exit 2
      fi
      SAMPLE_LIMIT="$2"
      shift
      ;;
    --benchmark|--benchmarks)
      if [[ $# -lt 2 ]]; then
        echo "$1 requires a benchmark name, comma-separated list, or all" >&2
        exit 2
      fi
      BENCHMARKS="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -d "$ROOT_DIR/hypha/.git" ]]; then
  echo "Missing Hypha checkout at $ROOT_DIR/hypha; run scripts/benchmarks/server_prepare_workcache.sh first." >&2
  exit 1
fi

NODE_MAJOR="$(node -p "Number(process.versions.node.split('.')[0])")"
if [[ "$NODE_MAJOR" -lt 18 ]]; then
  echo "Node.js >=18 is required by Hypha WorkCache; found $(node --version)." >&2
  echo "On AutoDL/conda hosts, one option is: conda install -y -c conda-forge nodejs=20" >&2
  exit 1
fi

if [[ ! -f "$ROOT_DIR/hypha/packages/workcache/dist/index.js" ]]; then
  echo "Missing Hypha WorkCache build at $ROOT_DIR/hypha/packages/workcache/dist/index.js" >&2
  echo "Run scripts/benchmarks/server_prepare_workcache.sh again, or run:" >&2
  echo "  cd $ROOT_DIR/hypha && npm ci --registry=https://registry.npmmirror.com --no-audit --no-fund --progress=false && npm run build --workspace @hypha/workcache" >&2
  exit 1
fi

if ! HYPHA_DIR_FOR_NODE="$ROOT_DIR/hypha" node <<'NODE'
const fs = require('fs');
const os = require('os');
const path = require('path');

const hyphaRoot = process.env.HYPHA_DIR_FOR_NODE;
const workcache = require(path.join(hyphaRoot, 'packages', 'workcache', 'dist'));
const filename = path.join(os.tmpdir(), `hypha-workcache-start-preflight-${process.pid}.sqlite`);

try {
  new workcache.SQLiteWorkCacheStore({ filename });
} catch (error) {
  console.error('Hypha WorkCache SQLite runtime unavailable.');
  console.error(error && error.stack ? error.stack : String(error));
  console.error('Install Node.js with node:sqlite support, or install better-sqlite3 in the Hypha checkout.');
  process.exit(1);
} finally {
  try {
    fs.unlinkSync(filename);
  } catch (_) {}
}
NODE
then
  exit 1
fi

if [[ ! -f "$ROOT_DIR/.env" && -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "Missing $ROOT_DIR/.env and DEEPSEEK_API_KEY is not set." >&2
  echo "Run server_prepare_workcache.sh with DEEPSEEK_API_KEY=..., or create .env from .env.server.template." >&2
  exit 1
fi

NORMALIZED_SAMPLE_LIMIT="$(printf '%s' "$SAMPLE_LIMIT" | tr '[:upper:]' '[:lower:]')"
if [[ "$NORMALIZED_SAMPLE_LIMIT" != "all" && ! "$SAMPLE_LIMIT" =~ ^[1-9][0-9]*$ ]]; then
  echo "--sample-limit must be a positive integer or all; got: $SAMPLE_LIMIT" >&2
  exit 2
fi

normalize_benchmarks() {
  local requested
  requested="$(printf '%s' "$1" | tr -d '[:space:]')"
  if [[ -z "$requested" ]]; then
    echo "--benchmarks must not be empty" >&2
    return 1
  fi
  if [[ "$(printf '%s' "$requested" | tr '[:upper:]' '[:lower:]')" == "all" ]]; then
    printf '%s\n' "$ALL_BENCHMARKS"
    return 0
  fi

  local IFS=','
  local parts=($requested)
  local selected=()
  local item
  for item in "${parts[@]}"; do
    case "$item" in
      tau2-bench|financebench|promptpg-tabmwp)
        selected+=("$item")
        ;;
      "")
        echo "Empty benchmark entry in: $1" >&2
        return 1
        ;;
      *)
        echo "Unknown benchmark: $item" >&2
        echo "Allowed: $ALL_BENCHMARKS" >&2
        return 1
        ;;
    esac
  done

  (IFS=','; printf '%s\n' "${selected[*]}")
}

normalize_method_suite() {
  local requested
  requested="$(printf '%s' "$1" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  case "$requested" in
    all)
      printf 'all\n'
      ;;
    1|table1|main)
      printf 'table1\n'
      ;;
    2|table2|ablation)
      printf 'table2\n'
      ;;
    3|table3|mechanism)
      printf 'table3\n'
      ;;
    *)
      echo "Unknown table experiment suite: $1" >&2
      echo "Allowed: table1, table2, table3, all" >&2
      return 1
      ;;
  esac
}

BENCHMARKS="$(normalize_benchmarks "$BENCHMARKS")"
METHOD_SUITE="$(normalize_method_suite "$METHOD_SUITE")"

if [[ -z "$EXP_ID" ]]; then
  if [[ "$METHOD_SUITE" == "all" ]]; then
    EXP_ID="real_hypha_all_50x2_server"
  else
    EXP_ID="real_hypha_${METHOD_SUITE}_50x2_server"
  fi
fi

CMD=(
  python3
  experiments/workcache_benchmarks/run_real_samples.py
  --sample-limit "$SAMPLE_LIMIT"
  --benchmarks "$BENCHMARKS"
  --method-suite "$METHOD_SUITE"
  --repeat-passes "$REPEAT_PASSES"
  --continue-on-task-error
  --tau2-timeout 300
  --tau2-subprocess-timeout 420
  --provider-timeout 180
  --provider-retries 2
  --provider-retry-backoff 2.0
  --exp-id "$EXP_ID"
)

if ((RESUME)); then
  CMD+=(--resume)
fi

cd "$ROOT_DIR"

if ((BACKGROUND)); then
  JOB_DIR="$ROOT_DIR/outputs/workcache_benchmarks/jobs"
  PID_FILE="$JOB_DIR/$EXP_ID.pid"
  LOG_FILE="$JOB_DIR/$EXP_ID.log"

  mkdir -p "$JOB_DIR"

  if [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE")"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" >/dev/null 2>&1; then
      echo "Benchmark already appears to be running with PID $existing_pid" >&2
      echo "PID file: $PID_FILE" >&2
      exit 1
    fi
  fi

  nohup "${CMD[@]}" >"$LOG_FILE" 2>&1 </dev/null &
  new_pid="$!"
  printf '%s\n' "$new_pid" >"$PID_FILE"

  echo "Started WorkCache benchmark in background."
  echo "PID: $new_pid"
  echo "Log: $LOG_FILE"
  echo "PID file: $PID_FILE"
  echo "Results: $ROOT_DIR/outputs/workcache_benchmarks/$EXP_ID"
else
  exec "${CMD[@]}"
fi
