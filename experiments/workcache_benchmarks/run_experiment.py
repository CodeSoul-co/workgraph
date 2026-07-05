#!/usr/bin/env python3
"""Run or simulate WorkCache benchmark experiments with fixed trace outputs.

The default simulate mode is for schema and pipeline validation only. It writes
complete trace files and derived tables without calling provider APIs. Real
agent adapters should write the same records so metrics can be recomputed
without rerunning tools or LLM calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from metrics import build_tables
from protocol import (
  AGENT_FLOWS,
  ALL_METHODS,
  BENCHMARK_TASK_FILES,
  DIRECT_BENCHMARKS,
  REQUIRED_TRACE_FILES,
  ROOT,
  TRACE_SCHEMA_VERSION,
  MethodSpec,
)


BASELINE_COST_PER_1K_INPUT = 0.00015
BASELINE_COST_PER_1K_OUTPUT = 0.00060

BENCHMARK_BASELINES = {
  "tau2-bench": {
    "llm_calls": 4,
    "tool_calls": 5,
    "input_tokens": 3200,
    "output_tokens": 650,
    "latency_ms": 52000,
    "success_rate": 0.70,
  },
  "financebench": {
    "llm_calls": 2,
    "tool_calls": 4,
    "input_tokens": 9500,
    "output_tokens": 520,
    "latency_ms": 38000,
    "success_rate": 0.74,
  },
  "promptpg-tabmwp": {
    "llm_calls": 1,
    "tool_calls": 2,
    "input_tokens": 1800,
    "output_tokens": 220,
    "latency_ms": 11000,
    "success_rate": 0.78,
  },
}

TREE_TYPES = (
  "PromptPrefixTree",
  "PlanTree",
  "ToolTree",
  "ObservationTree",
  "VerificationTree",
)


def stable_int(*parts: object, modulo: int = 10_000) -> int:
  payload = "::".join(str(part) for part in parts)
  digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
  return int(digest[:12], 16) % modulo


def stable_hash(value: object) -> str:
  return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def slug(value: str) -> str:
  return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
  if not path.exists():
    raise FileNotFoundError(
      f"missing task slice {path}; run scripts/benchmarks/export_eval_slices.py first"
    )
  rows: list[dict[str, Any]] = []
  with path.open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        rows.append(json.loads(line))
  return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as handle:
    for row in rows:
      handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def hypha_commit() -> str | None:
  hypha = ROOT / "hypha"
  if not hypha.exists():
    hypha = ROOT.parent / "Hypha"
  try:
    return subprocess.check_output(["git", "-C", str(hypha), "rev-parse", "HEAD"], text=True).strip()
  except Exception:
    return None


def load_tasks(benchmarks: list[str], limit: int | None) -> dict[str, list[dict[str, Any]]]:
  tasks: dict[str, list[dict[str, Any]]] = {}
  for benchmark in benchmarks:
    rows = read_jsonl(BENCHMARK_TASK_FILES[benchmark])
    tasks[benchmark] = rows[:limit] if limit is not None else rows
  return tasks


def prepare_run_dir(run_dir: Path) -> None:
  for rel_path in REQUIRED_TRACE_FILES:
    (run_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)
  for rel_dir in (
    "payloads/tool_outputs",
    "payloads/file_snapshots",
    "payloads/test_logs",
    "payloads/llm_responses",
    "prompts/prompt_texts",
    "derived",
  ):
    (run_dir / rel_dir).mkdir(parents=True, exist_ok=True)


def method_profile(method: MethodSpec) -> dict[str, float]:
  config = method.cache_config
  cache_enabled = any(config[tree] for tree in TREE_TYPES)
  cache_strength = sum(1 for tree in TREE_TYPES if config[tree]) / len(TREE_TYPES)
  workgraph_bonus = 0.12 if config["WorkGraphDemand"] else 0.0
  utility_bonus = 0.08 if config["TreeUtilityPropagation"] else 0.0
  validity_penalty = 0.08 if not config["ValidityRules"] and cache_enabled else 0.0

  return {
    "hit_rate": max(0.0, min(0.88, 0.18 + cache_strength * 0.42 + workgraph_bonus + utility_bonus))
    if cache_enabled
    else 0.0,
    "input_factor": max(0.42, 1.0 - 0.18 * config["PromptPrefixTree"] - 0.08 * config["PlanTree"]),
    "llm_factor": max(0.45, 1.0 - 0.18 * config["PlanTree"] - 0.08 * config["PromptPrefixTree"]),
    "tool_factor": max(
      0.35,
      1.0 - 0.30 * config["ToolTree"] - 0.12 * config["ObservationTree"] - 0.08 * config["VerificationTree"],
    ),
    "latency_factor": max(
      0.35,
      1.0
      - 0.16 * config["ToolTree"]
      - 0.10 * config["ObservationTree"]
      - 0.10 * config["VerificationTree"]
      - workgraph_bonus,
    ),
    "success_delta": -validity_penalty,
    "stale_rate": 0.22 if not config["ValidityRules"] and cache_enabled else 0.015,
    "lookup_ms": 3.0 + cache_strength * 3.0,
    "eviction_mistake_rate": max(0.02, 0.20 - workgraph_bonus - utility_bonus),
  }


def cost_usd(input_tokens: int, output_tokens: int) -> float:
  return (input_tokens / 1000.0) * BASELINE_COST_PER_1K_INPUT + (
    output_tokens / 1000.0
  ) * BASELINE_COST_PER_1K_OUTPUT


def task_complexity(task: dict[str, Any]) -> int:
  return max(1, len(json.dumps(task.get("input", {}), ensure_ascii=False)) // 600)


def simulate_method_task(
  records: dict[str, list[dict[str, Any]]],
  exp_id: str,
  method: MethodSpec,
  benchmark: str,
  task: dict[str, Any],
  index: int,
) -> None:
  profile = method_profile(method)
  baseline = BENCHMARK_BASELINES[benchmark]
  task_id = str(task["task_id"])
  run_id = f"{exp_id}:{slug(method.name)}:{benchmark}:{slug(task_id)}"
  agent_id = f"agent.{benchmark}"
  complexity = task_complexity(task)
  prompt_hash = stable_hash({"benchmark": benchmark, "prompt": AGENT_FLOWS[benchmark]["prompt"]})
  input_hash = stable_hash(task["input"])

  base_llm_calls = int(baseline["llm_calls"])
  base_tool_calls = int(baseline["tool_calls"])
  executed_llm_calls = max(1, round(base_llm_calls * profile["llm_factor"]))
  executed_tool_calls = max(0, round(base_tool_calls * profile["tool_factor"]))
  success_threshold = int(10_000 * max(0.0, min(1.0, baseline["success_rate"] + profile["success_delta"])))
  success = stable_int(method.name, benchmark, task_id, "success") < success_threshold

  latency_ms = round(float(baseline["latency_ms"]) * profile["latency_factor"] + complexity * 175)
  records["raw/task_results.jsonl"].append(
    {
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "agent_id": agent_id,
      "success": success,
      "latency_ms": latency_ms,
      "mode": "simulate",
      "final_answer_hash": stable_hash({"method": method.name, "task_id": task_id, "success": success}),
      "evaluator": AGENT_FLOWS[benchmark]["preferred_evaluator"],
    }
  )

  records["raw/runtime_events.jsonl"].append(
    {
      "event_id": f"evt:{run_id}:start",
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "timestamp": index,
      "event_type": "agent.run.started",
      "agent_id": agent_id,
      "payload": {"trace_schema_version": TRACE_SCHEMA_VERSION},
    }
  )

  stable_prefix_tokens = int(float(baseline["input_tokens"]) * 0.55)
  dynamic_tokens = int(float(baseline["input_tokens"]) * 0.45) + complexity * 20
  records["prompts/prompt_assemblies.jsonl"].append(
    {
      "prompt_id": f"prompt:{run_id}",
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "llm_call_id": f"llm:{run_id}:0",
      "stable_prefix_hash": prompt_hash,
      "stable_prefix_tokens": stable_prefix_tokens,
      "dynamic_suffix_hash": input_hash,
      "dynamic_suffix_tokens": dynamic_tokens,
      "blocks": [
        {
          "block_id": f"prompt-template:{benchmark}",
          "tree_type": "PromptPrefixTree",
          "position": "stable_prefix",
          "token_count": stable_prefix_tokens,
          "hash": prompt_hash,
        },
        {
          "block_id": f"task-input:{task_id}",
          "tree_type": "ObservationTree",
          "position": "dynamic_suffix",
          "token_count": dynamic_tokens,
          "hash": input_hash,
        },
      ],
    }
  )

  for llm_index in range(base_llm_calls):
    executed = llm_index < executed_llm_calls
    input_tokens = int((float(baseline["input_tokens"]) * profile["input_factor"]) / max(1, executed_llm_calls))
    output_tokens = int(float(baseline["output_tokens"]) / max(1, executed_llm_calls))
    records["raw/llm_calls.jsonl"].append(
      {
        "llm_call_id": f"llm:{run_id}:{llm_index}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "provider": "configured-provider",
        "model": "configured-model",
        "request_hash": stable_hash({"run_id": run_id, "llm_index": llm_index}),
        "prefix_hash": prompt_hash,
        "dynamic_suffix_hash": input_hash,
        "input_tokens": input_tokens if executed else 0,
        "output_tokens": output_tokens if executed else 0,
        "cached_input_tokens": int(input_tokens * profile["hit_rate"]) if executed else input_tokens,
        "latency_ms": round(latency_ms / max(1, executed_llm_calls)) if executed else 0,
        "ttft_ms": 0 if not executed else 350 + stable_int(run_id, llm_index, modulo=150),
        "cost_usd": cost_usd(input_tokens, output_tokens) if executed else 0,
        "cache_status": "miss" if executed else "hit",
        "executed": executed,
      }
    )

  for tool_index in range(base_tool_calls):
    executed = tool_index < executed_tool_calls
    tool_name = AGENT_FLOWS[benchmark]["tools"][tool_index % len(AGENT_FLOWS[benchmark]["tools"])]
    records["raw/tool_calls.jsonl"].append(
      {
        "tool_call_id": f"tool:{run_id}:{tool_index}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "tool_name": tool_name,
        "args_hash": stable_hash({"tool": tool_name, "task_id": task_id}),
        "latency_ms": 900 + stable_int(run_id, tool_index, modulo=2400) if executed else 0,
        "cache_status": "miss" if executed else "hit",
        "tree_type": "ToolTree",
        "block_id": f"block:tool:{benchmark}:{tool_index}",
        "result_hash": stable_hash({"tool": tool_name, "task_id": task_id, "executed": executed}),
        "result_ref": f"payloads/tool_outputs/{slug(run_id)}_{tool_index}.json",
        "executed": executed,
      }
    )

  for tree_index, tree_type in enumerate(TREE_TYPES):
    enabled = bool(method.cache_config[tree_type])
    hit = enabled and stable_int(method.name, benchmark, task_id, tree_type) < int(profile["hit_rate"] * 10_000)
    stale = hit and stable_int(method.name, task_id, tree_type, "stale") < int(profile["stale_rate"] * 10_000)
    records["cache/cache_ops.jsonl"].append(
      {
        "cache_event_id": f"cache:{run_id}:{tree_type}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "type": "cache.lookup",
        "tree_type": tree_type,
        "key": stable_hash({"tree_type": tree_type, "task_id": task_id}),
        "node_id": f"node:{run_id}:{tree_index}",
        "result": "hit" if hit else "miss" if enabled else "disabled",
        "block_id": f"block:{tree_type}:{benchmark}:{task_id}",
        "miss_reason": None if hit else "not_found" if enabled else "disabled",
        "validation_result": "stale" if stale else "valid" if hit else None,
        "stale": stale,
        "latency_ms": round(profile["lookup_ms"] + stable_int(run_id, tree_type, modulo=30) / 10.0, 2),
      }
    )
    records["cache/validity_checks.jsonl"].append(
      {
        "validation_id": f"val:{run_id}:{tree_type}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "block_id": f"block:{tree_type}:{benchmark}:{task_id}",
        "tree_type": tree_type,
        "rules": [{"type": "fingerprint_unchanged", "passed": method.cache_config["ValidityRules"]}],
        "result": "valid" if method.cache_config["ValidityRules"] else "skipped",
        "latency_ms": 2,
      }
    )

  step_names = ("observe", "plan", "act", "verify")
  for step_index, step_name in enumerate(step_names):
    cache_status = "hit" if step_index < executed_tool_calls and profile["hit_rate"] > 0.35 else "miss"
    records["graph/work_graph_nodes.jsonl"].append(
      {
        "node_id": f"node:{run_id}:{step_index}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "event_type": f"{step_name}.completed",
        "node_type": step_name,
        "primary_tree_type": TREE_TYPES[step_index % len(TREE_TYPES)],
        "operation": step_name,
        "step_index": step_index,
        "agent_id": agent_id,
        "input_refs": [f"node:{run_id}:{step_index - 1}"] if step_index else [],
        "output_block_ids": [f"block:{run_id}:{step_index}"],
        "critical_path": True,
        "cache_status": cache_status,
      }
    )
    if step_index:
      records["graph/work_graph_edges.jsonl"].append(
        {
          "edge_id": f"edge:{run_id}:{step_index - 1}:{step_index}",
          "run_id": run_id,
          "task_id": task_id,
          "benchmark": benchmark,
          "method": method.name,
          "from": f"node:{run_id}:{step_index - 1}",
          "to": f"node:{run_id}:{step_index}",
          "edge_type": "control",
          "weight": 1.0,
        }
      )

  demand_enabled = bool(method.cache_config["WorkGraphDemand"])
  for signal_index, tree_type in enumerate(("PlanTree", "ToolTree", "VerificationTree")):
    actual_needed = True
    predicted = demand_enabled
    actual_used = predicted and stable_int(method.name, task_id, tree_type, "use") < int(profile["hit_rate"] * 10_000)
    records["graph/demand_signals.jsonl"].append(
      {
        "signal_id": f"sig:{run_id}:{signal_index}",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "source_node_id": f"node:{run_id}:1",
        "target_tree_type": tree_type,
        "target_key": stable_hash({"target": tree_type, "task_id": task_id}),
        "target_block_id": f"block:{tree_type}:{task_id}",
        "steps_to_use_pred": signal_index + 1 if predicted else None,
        "demand_score": round(profile["hit_rate"], 4) if predicted else 0.0,
        "reason": "future path demand" if predicted else "demand disabled",
        "created_at_step": 1,
        "expires_at_step": 6,
        "predicted": predicted,
        "actual_needed": actual_needed,
        "actual_used": actual_used,
        "actual_steps_to_use": signal_index + 2 if actual_used else None,
      }
    )

  if any(method.cache_config[tree] for tree in TREE_TYPES):
    recomputed = stable_int(method.name, task_id, "evict") < int(profile["eviction_mistake_rate"] * 10_000)
    records["cache/evictions.jsonl"].append(
      {
        "event_type": "cache.evict",
        "run_id": run_id,
        "task_id": task_id,
        "benchmark": benchmark,
        "method": method.name,
        "tree_type": "ToolTree",
        "block_id": f"block:evicted:{run_id}",
        "reason": "low_utility",
        "utility": round(profile["hit_rate"], 4),
        "last_used_at": index,
        "evicted_at": index + 1,
        "recomputed_after_eviction": recomputed,
        "steps_after_eviction": 2 if recomputed else None,
      }
    )

  records["raw/observations.jsonl"].append(
    {
      "observation_id": f"obs:{run_id}",
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "type": "task.input",
      "content_hash": input_hash,
      "cache_status": "hit" if profile["hit_rate"] > 0.5 else "miss",
      "block_id": f"obs:block:{task_id}",
    }
  )
  records["raw/verifications.jsonl"].append(
    {
      "verification_id": f"ver:{run_id}",
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "type": "benchmark_judge",
      "command": AGENT_FLOWS[benchmark]["preferred_evaluator"],
      "result": "pass" if success else "fail",
      "latency_ms": 250 + stable_int(run_id, "judge", modulo=1000),
      "cache_status": "hit" if method.cache_config["VerificationTree"] and profile["hit_rate"] > 0.5 else "miss",
      "block_id": f"ver:block:{task_id}",
    }
  )
  records["cache/tree_updates.jsonl"].append(
    {
      "tree_update_id": f"tree:{run_id}",
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "tree_type": "ToolTree",
      "trigger_event_id": f"cache:{run_id}:ToolTree",
      "updated_path": [
        {
          "node_id": f"node:{run_id}:2",
          "local_utility_before": 0.2,
          "local_utility_after": round(0.2 + profile["hit_rate"], 4),
          "aggregate_utility_before": 0.2,
          "aggregate_utility_after": round(0.2 + profile["hit_rate"], 4),
        }
      ],
      "latency_ms": 4,
    }
  )
  records["raw/runtime_events.jsonl"].append(
    {
      "event_id": f"evt:{run_id}:finish",
      "run_id": run_id,
      "task_id": task_id,
      "benchmark": benchmark,
      "method": method.name,
      "timestamp": index + 1,
      "event_type": "agent.run.finished",
      "agent_id": agent_id,
      "payload": {"success": success, "latency_ms": latency_ms},
    }
  )


def write_config(run_dir: Path, exp_id: str, mode: str, tasks: dict[str, list[dict[str, Any]]]) -> None:
  config = {
    "experiment_id": exp_id,
    "mode": mode,
    "trace_schema_version": TRACE_SCHEMA_VERSION,
    "benchmarks": list(tasks.keys()),
    "task_counts": {benchmark: len(rows) for benchmark, rows in tasks.items()},
    "method_order": [method.name for method in ALL_METHODS],
    "agent_flows": AGENT_FLOWS,
    "hypha_commit": hypha_commit(),
    "timestamp": int(time.time()),
    "note": "simulate mode validates trace and table schemas only; do not report it as empirical performance.",
  }
  (run_dir / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_simulation(run_dir: Path, exp_id: str, tasks: dict[str, list[dict[str, Any]]]) -> None:
  records = {rel_path: [] for rel_path in REQUIRED_TRACE_FILES if rel_path != "config.json"}
  sequence = 0
  for method in ALL_METHODS:
    for benchmark, benchmark_tasks in tasks.items():
      for task in benchmark_tasks:
        simulate_method_task(records, exp_id, method, benchmark, task, sequence)
        sequence += 10
  for rel_path, rows in records.items():
    write_jsonl(run_dir / rel_path, rows)


def parse_benchmarks(raw: str) -> list[str]:
  if raw == "direct":
    return list(DIRECT_BENCHMARKS)
  benchmarks = [item.strip() for item in raw.split(",") if item.strip()]
  unknown = [benchmark for benchmark in benchmarks if benchmark not in DIRECT_BENCHMARKS]
  if unknown:
    raise ValueError(f"unsupported direct benchmark(s): {', '.join(unknown)}")
  return benchmarks


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--exp-id", default=f"exp_{time.strftime('%Y%m%d_%H%M%S')}_workcache")
  parser.add_argument("--benchmarks", default="direct")
  parser.add_argument("--limit", type=int, default=2)
  parser.add_argument("--mode", choices=["simulate"], default="simulate")
  parser.add_argument(
    "--output-dir",
    type=Path,
    default=ROOT / "outputs" / "workcache_benchmarks",
  )
  args = parser.parse_args()

  benchmarks = parse_benchmarks(args.benchmarks)
  tasks = load_tasks(benchmarks, args.limit)
  run_dir = args.output_dir / args.exp_id
  prepare_run_dir(run_dir)
  write_config(run_dir, args.exp_id, args.mode, tasks)
  run_simulation(run_dir, args.exp_id, tasks)
  table_paths = build_tables(run_dir)

  print(f"run_dir: {run_dir}")
  for name, path in table_paths.items():
    print(f"{name}: {path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())

