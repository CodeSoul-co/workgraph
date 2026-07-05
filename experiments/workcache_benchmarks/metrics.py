#!/usr/bin/env python3
"""Derive fixed WorkCache experiment tables from saved traces."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from protocol import (
  TABLE1_COLUMNS,
  TABLE1_METHODS,
  TABLE2_COLUMNS,
  TABLE2_METHODS,
  TABLE3_COLUMNS,
  TABLE3_METHODS,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
  if not path.exists():
    return []
  rows: list[dict[str, Any]] = []
  with path.open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        rows.append(json.loads(line))
  return rows


def write_csv(path: Path, columns: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(columns))
    writer.writeheader()
    for row in rows:
      writer.writerow({column: row.get(column, "") for column in writer.fieldnames})


def number(value: Any) -> float:
  return float(value) if isinstance(value, (int, float)) else 0.0


def bool_value(value: Any) -> bool:
  return bool(value) if isinstance(value, bool) else False


def ratio(numerator: float, denominator: float) -> str:
  if denominator <= 0:
    return ""
  return f"{numerator / denominator:.4f}"


def money(value: float) -> str:
  return f"{value:.6f}"


def integer(value: float) -> str:
  return str(int(round(value)))


def milliseconds(value: float) -> str:
  return f"{value:.2f}"


def percentile(values: list[float], p: float) -> float:
  if not values:
    return 0.0
  ordered = sorted(values)
  index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
  return ordered[index]


def group_by_method(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
  grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
  for row in rows:
    method = str(row.get("method", ""))
    if method:
      grouped[method].append(row)
  return grouped


def load_trace(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
  return {
    "llm_calls": read_jsonl(run_dir / "raw" / "llm_calls.jsonl"),
    "tool_calls": read_jsonl(run_dir / "raw" / "tool_calls.jsonl"),
    "task_results": read_jsonl(run_dir / "raw" / "task_results.jsonl"),
    "cache_ops": read_jsonl(run_dir / "cache" / "cache_ops.jsonl"),
    "demand_signals": read_jsonl(run_dir / "graph" / "demand_signals.jsonl"),
    "work_graph_nodes": read_jsonl(run_dir / "graph" / "work_graph_nodes.jsonl"),
    "evictions": read_jsonl(run_dir / "cache" / "evictions.jsonl"),
  }


def aggregate_method_metrics(trace: dict[str, list[dict[str, Any]]], method: str) -> dict[str, str]:
  llm_calls = group_by_method(trace["llm_calls"]).get(method, [])
  tool_calls = group_by_method(trace["tool_calls"]).get(method, [])
  task_results = group_by_method(trace["task_results"]).get(method, [])
  cache_ops = group_by_method(trace["cache_ops"]).get(method, [])

  executed_llm = [row for row in llm_calls if bool_value(row.get("executed"))]
  executed_tools = [row for row in tool_calls if bool_value(row.get("executed"))]
  cache_hits = [row for row in cache_ops if row.get("result") == "hit"]
  stale_hits = [
    row
    for row in cache_hits
    if row.get("validation_result") == "stale" or bool_value(row.get("stale"))
  ]

  total_tasks = len(task_results)
  success_count = sum(1 for row in task_results if bool_value(row.get("success")))

  return {
    "API Cost": money(sum(number(row.get("cost_usd")) for row in executed_llm)),
    "Input Tokens": integer(sum(number(row.get("input_tokens")) for row in executed_llm)),
    "LLM Calls": integer(len(executed_llm)),
    "Tool Calls": integer(len(executed_tools)),
    "Job Time": milliseconds(sum(number(row.get("latency_ms")) for row in task_results)),
    "Stale Hit Rate": ratio(len(stale_hits), len(cache_hits)),
    "Success Rate": ratio(success_count, total_tasks),
  }


def mechanism_metrics(trace: dict[str, list[dict[str, Any]]], method: str) -> dict[str, str]:
  signals = group_by_method(trace["demand_signals"]).get(method, [])
  nodes = group_by_method(trace["work_graph_nodes"]).get(method, [])
  cache_ops = group_by_method(trace["cache_ops"]).get(method, [])
  evictions = group_by_method(trace["evictions"]).get(method, [])

  predicted = [row for row in signals if bool_value(row.get("predicted"))]
  actual_used = [row for row in predicted if bool_value(row.get("actual_used"))]
  actual_needed = [row for row in signals if bool_value(row.get("actual_needed"))]
  covered_needed = [row for row in actual_needed if bool_value(row.get("predicted"))]

  critical_nodes = [
    row
    for row in nodes
    if bool_value(row.get("critical_path")) and row.get("cache_status") != "bypass"
  ]
  critical_hits = [row for row in critical_nodes if row.get("cache_status") == "hit"]
  mistaken_evictions = [
    row for row in evictions if bool_value(row.get("recomputed_after_eviction"))
  ]
  lookup_latencies = [
    number(row.get("latency_ms"))
    for row in cache_ops
    if row.get("result") == "lookup"
  ]

  return {
    "Demand Precision": ratio(len(actual_used), len(predicted)),
    "Demand Recall": ratio(len(covered_needed), len(actual_needed)),
    "Critical Path Hit Rate": ratio(len(critical_hits), len(critical_nodes)),
    "Eviction Mistake Rate": ratio(len(mistaken_evictions), len(evictions)),
    "Tree Lookup p95": milliseconds(percentile(lookup_latencies, 0.95)),
  }


def build_tables(run_dir: Path) -> dict[str, Path]:
  trace = load_trace(run_dir)
  derived = run_dir / "derived"

  table1_rows = []
  for method in TABLE1_METHODS:
    row = {"Method": method.name}
    row.update(aggregate_method_metrics(trace, method.name))
    table1_rows.append(row)

  table2_rows = []
  for method in TABLE2_METHODS:
    row = {"Method": method.name, "Removed Component": method.removed_component}
    row.update(aggregate_method_metrics(trace, method.name))
    table2_rows.append(row)

  table3_rows = []
  for method in TABLE3_METHODS:
    row = {"Method": method.name}
    row.update(mechanism_metrics(trace, method.name))
    table3_rows.append(row)

  outputs = {
    "table1_main_results": derived / "table1_main_results.csv",
    "table2_ablation_results": derived / "table2_ablation_results.csv",
    "table3_mechanism_results": derived / "table3_mechanism_results.csv",
  }
  write_csv(outputs["table1_main_results"], TABLE1_COLUMNS, table1_rows)
  write_csv(outputs["table2_ablation_results"], TABLE2_COLUMNS, table2_rows)
  write_csv(outputs["table3_mechanism_results"], TABLE3_COLUMNS, table3_rows)
  return outputs


def main() -> int:
  import argparse

  parser = argparse.ArgumentParser()
  parser.add_argument("run_dir", type=Path)
  args = parser.parse_args()
  outputs = build_tables(args.run_dir)
  for name, path in outputs.items():
    print(f"{name}: {path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
