#!/usr/bin/env python3
"""Lightweight validation for prepared benchmark assets."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ok(message: str) -> None:
  print(f"ok: {message}")


def warn(message: str) -> None:
  print(f"warn: {message}")


def fail(message: str) -> None:
  print(f"fail: {message}")


def git_head(path: Path) -> str | None:
  if not (path / ".git").exists():
    return None
  return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def check_tau2() -> bool:
  root = ROOT / "external" / "benchmarks" / "tau2-bench"
  head = git_head(root)
  if not head:
    fail("tau2-bench checkout missing")
    return False
  domains = root / "data" / "tau2" / "domains"
  task_files = sorted(path.parent.name for path in domains.glob("*/tasks.json"))
  ok(f"tau2-bench checkout {head}; task domains={task_files}")
  tau2_bin = root / ".venv" / "bin" / "tau2"
  if tau2_bin.exists():
    ok("tau2-bench uv environment exists")
  else:
    warn("tau2-bench uv environment missing; run scripts/benchmarks/bootstrap.sh env-tau2")
  return True


def check_webarena() -> bool:
  root = ROOT / "external" / "benchmarks" / "webarena"
  head = git_head(root)
  if not head:
    fail("WebArena checkout missing")
    return False
  raw = root / "config_files" / "test.raw.json"
  data = json.loads(raw.read_text(encoding="utf-8"))
  ok(f"WebArena checkout {head}; raw tasks={len(data)}")
  python = root / ".venv" / "bin" / "python"
  if python.exists():
    result = subprocess.run(
      [str(python), "-c", "import browser_env"],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      check=False,
    )
    if result.returncode == 0:
      ok("WebArena environment imports browser_env")
    else:
      warn("WebArena venv exists but browser_env import fails; see benchmarks/status.md")
  else:
    warn("WebArena venv missing; run scripts/benchmarks/bootstrap.sh env-webarena on a compatible host")
  return True


def check_financebench() -> bool:
  root = ROOT / "data" / "raw" / "benchmarks" / "financebench"
  jsonl = root / "financebench_merged.jsonl"
  if not jsonl.exists():
    fail("FinanceBench JSONL missing")
    return False
  rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
  docs = {f"{row['doc_name']}.pdf" for row in rows}
  pdfs = [path.name for path in (root / "pdfs").glob("*.pdf")]
  ok(f"FinanceBench rows={len(rows)}; referenced_pdfs={len(docs)}; downloaded_pdfs={len(pdfs)}")
  missing = sorted(docs - set(pdfs))
  if missing:
    warn(f"FinanceBench missing referenced PDFs: {len(missing)}")
  return True


def check_promptpg() -> bool:
  root = ROOT / "external" / "benchmarks" / "PromptPG"
  head = git_head(root)
  if not head:
    fail("PromptPG checkout missing")
    return False
  tabmwp = root / "data" / "tabmwp"
  counts = {}
  for name in ["problems_train.json", "problems_dev.json", "problems_test.json", "problems_test1k.json"]:
    path = tabmwp / name
    counts[name] = len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
  table_count = sum(1 for _ in (tabmwp / "tables").glob("*.png"))
  ok(f"PromptPG checkout {head}; splits={counts}; table_images={table_count}")
  python = root / ".venv" / "bin" / "python"
  if python.exists():
    result = subprocess.run(
      [str(python), "-c", "import transformers, openai, pandas"],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      check=False,
    )
    if result.returncode == 0:
      ok("PromptPG environment imports core dependencies")
    else:
      warn("PromptPG venv exists but core dependency import fails; see benchmarks/status.md")
  else:
    warn("PromptPG venv missing; run scripts/benchmarks/bootstrap.sh env-promptpg on a compatible host")
  return True


def main() -> int:
  checks = [check_tau2, check_webarena, check_financebench, check_promptpg]
  results = [check() for check in checks]
  return 0 if all(results) else 1


if __name__ == "__main__":
  sys.exit(main())
