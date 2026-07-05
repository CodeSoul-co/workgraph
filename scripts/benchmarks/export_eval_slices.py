#!/usr/bin/env python3
"""Export evaluation-only task slices from local benchmark assets.

The exported JSONL records are a neutral Workgraph format. They are intended for
fair evaluation orchestration, not for training benchmark-specific policies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "benchmarks" / "eval_slices"


def read_json(path: Path) -> Any:
  with path.open("r", encoding="utf-8") as handle:
    return json.load(handle)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
  with path.open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], limit: int | None) -> int:
  path.parent.mkdir(parents=True, exist_ok=True)
  count = 0
  with path.open("w", encoding="utf-8") as handle:
    for row in rows:
      if limit is not None and count >= limit:
        break
      handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
      count += 1
  return count


def export_tau2(domain: str) -> Iterable[dict[str, Any]]:
  domains_root = ROOT / "external" / "benchmarks" / "tau2-bench" / "data" / "tau2" / "domains"
  domains = sorted(path.name for path in domains_root.iterdir() if path.is_dir()) if domain == "all" else [domain]
  for domain_name in domains:
    tasks_path = domains_root / domain_name / "tasks.json"
    if not tasks_path.exists():
      continue
    tasks = read_json(tasks_path)
    for task in tasks:
      task_id = str(task.get("id"))
      yield {
        "benchmark": "tau2-bench",
        "task_id": f"{domain_name}:{task_id}",
        "input": {
          "domain": domain_name,
          "description": task.get("description"),
          "user_scenario": task.get("user_scenario"),
          "initial_state": task.get("initial_state"),
        },
        "gold": {
          "evaluation_criteria": task.get("evaluation_criteria"),
        },
        "metadata": {
          "source_path": str(tasks_path.relative_to(ROOT)),
          "requires_llm_user_simulator": True,
          "requires_training": False,
        },
      }


def export_webarena() -> Iterable[dict[str, Any]]:
  path = ROOT / "external" / "benchmarks" / "webarena" / "config_files" / "test.raw.json"
  tasks = read_json(path)
  for task in tasks:
    yield {
      "benchmark": "webarena",
      "task_id": str(task["task_id"]),
      "input": {
        "intent": task.get("intent"),
        "intent_template": task.get("intent_template"),
        "instantiation_dict": task.get("instantiation_dict"),
        "sites": task.get("sites"),
        "start_url": task.get("start_url"),
        "require_login": task.get("require_login"),
        "require_reset": task.get("require_reset"),
        "storage_state": task.get("storage_state"),
        "geolocation": task.get("geolocation"),
      },
      "gold": {
        "eval": task.get("eval"),
      },
      "metadata": {
        "source_path": str(path.relative_to(ROOT)),
        "requires_browser": True,
        "requires_self_hosted_sites": True,
        "requires_training": False,
      },
    }


def export_financebench() -> Iterable[dict[str, Any]]:
  path = ROOT / "data" / "raw" / "benchmarks" / "financebench" / "financebench_merged.jsonl"
  pdf_root = ROOT / "data" / "raw" / "benchmarks" / "financebench" / "pdfs"
  for row in read_jsonl(path):
    doc_name = row["doc_name"]
    yield {
      "benchmark": "financebench",
      "task_id": row["financebench_id"],
      "input": {
        "question": row.get("question"),
        "company": row.get("company"),
        "document": {
          "doc_name": doc_name,
          "doc_type": row.get("doc_type"),
          "doc_period": row.get("doc_period"),
          "pdf_path": str((pdf_root / f"{doc_name}.pdf").relative_to(ROOT)),
          "doc_link": row.get("doc_link"),
        },
      },
      "gold": {
        "answer": row.get("answer"),
        "justification": row.get("justification"),
        "evidence": row.get("evidence"),
      },
      "metadata": {
        "source_path": str(path.relative_to(ROOT)),
        "question_type": row.get("question_type"),
        "question_reasoning": row.get("question_reasoning"),
        "dataset_subset_label": row.get("dataset_subset_label"),
        "license": "cc-by-nc-4.0",
        "requires_retrieval_or_long_context": True,
        "requires_training": False,
      },
    }


def export_promptpg(split: str) -> Iterable[dict[str, Any]]:
  path = ROOT / "external" / "benchmarks" / "PromptPG" / "data" / "tabmwp" / f"problems_{split}.json"
  problems = read_json(path)
  for problem_id, problem in problems.items():
    yield {
      "benchmark": "promptpg-tabmwp",
      "task_id": str(problem_id),
      "input": {
        "question": problem.get("question"),
        "choices": problem.get("choices"),
        "unit": problem.get("unit"),
        "table_title": problem.get("table_title"),
        "table": problem.get("table"),
        "table_for_pd": problem.get("table_for_pd"),
      },
      "gold": {
        "answer": problem.get("answer"),
        "solution": problem.get("solution"),
      },
      "metadata": {
        "source_path": str(path.relative_to(ROOT)),
        "split": problem.get("split", split),
        "ques_type": problem.get("ques_type"),
        "ans_type": problem.get("ans_type"),
        "grade": problem.get("grade"),
        "row_num": problem.get("row_num"),
        "column_num": problem.get("column_num"),
        "requires_training": False,
      },
    }


def export_one(args: argparse.Namespace, benchmark: str) -> tuple[Path, int]:
  if benchmark == "tau2":
    rows = export_tau2(args.tau2_domain)
    name = f"tau2_{args.tau2_domain}.jsonl"
  elif benchmark == "webarena":
    rows = export_webarena()
    name = "webarena.jsonl"
  elif benchmark == "financebench":
    rows = export_financebench()
    name = "financebench.jsonl"
  elif benchmark == "promptpg":
    rows = export_promptpg(args.promptpg_split)
    name = f"promptpg_tabmwp_{args.promptpg_split}.jsonl"
  else:
    raise ValueError(f"unsupported benchmark: {benchmark}")

  output_path = args.output_dir / name
  count = write_jsonl(output_path, rows, args.limit)
  return output_path, count


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument(
    "--benchmark",
    choices=["all", "tau2", "webarena", "financebench", "promptpg"],
    default="all",
  )
  parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
  parser.add_argument("--limit", type=int, default=None)
  parser.add_argument("--tau2-domain", default="all")
  parser.add_argument(
    "--promptpg-split",
    choices=["train", "dev", "test", "test1k"],
    default="test1k",
  )
  args = parser.parse_args()
  if not args.output_dir.is_absolute():
    args.output_dir = ROOT / args.output_dir

  benchmarks = ["tau2", "webarena", "financebench", "promptpg"] if args.benchmark == "all" else [args.benchmark]
  for benchmark in benchmarks:
    path, count = export_one(args, benchmark)
    print(f"{benchmark}: wrote {count} tasks to {path.relative_to(ROOT)}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
