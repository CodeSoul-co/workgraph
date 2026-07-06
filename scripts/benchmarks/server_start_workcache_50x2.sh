#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP_ID="${WORKCACHE_EXP_ID:-real_hypha_all_50x2_server}"
SAMPLE_LIMIT="${WORKCACHE_SAMPLE_LIMIT:-${WORKCACHE_LIMIT:-50}}"
BENCHMARKS="${WORKCACHE_BENCHMARKS:-tau2-bench,financebench,promptpg-tabmwp}"
REPEAT_PASSES="${WORKCACHE_REPEAT_PASSES:-2}"
BACKGROUND=0
RESUME=0

usage() {
  cat <<'EOF'
Usage: scripts/benchmarks/server_start_workcache_50x2.sh [--background] [--resume]
       scripts/benchmarks/server_start_workcache_50x2.sh [--sample-limit N|all]

Environment overrides:
  WORKCACHE_EXP_ID          default: real_hypha_all_50x2_server
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
    --sample-limit|--limit)
      if [[ $# -lt 2 ]]; then
        echo "$1 requires a value: positive integer or all" >&2
        exit 2
      fi
      SAMPLE_LIMIT="$2"
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

CMD=(
  python3
  experiments/workcache_benchmarks/run_real_samples.py
  --sample-limit "$SAMPLE_LIMIT"
  --benchmarks "$BENCHMARKS"
  --method-suite all
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
