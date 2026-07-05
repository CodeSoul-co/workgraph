#!/usr/bin/env python3
"""Check benchmark tool readiness without running paid model calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def print_result(status: str, item: str, detail: str = "") -> None:
  suffix = f" - {detail}" if detail else ""
  print(f"{status}: {item}{suffix}")


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
  merged_env = os.environ.copy()
  if env:
    merged_env.update(env)
  return subprocess.run(
    command,
    cwd=str(cwd) if cwd else None,
    env=merged_env,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
  )


def command_exists(name: str) -> bool:
  return shutil.which(name) is not None


def check_system_tools() -> bool:
  ok = True
  for name in ["uv", "docker", "node", "npm", "gh", "pdftotext", "rg", "srt"]:
    if command_exists(name):
      print_result("ok", f"system tool {name}", shutil.which(name) or "")
    else:
      print_result("missing", f"system tool {name}")
      ok = False
  return ok


def check_tau2_tools() -> bool:
  tau2_dir = ROOT / "external" / "benchmarks" / "tau2-bench"
  code = """
import gymnasium
import rank_bm25
from tau2.knowledge.sandbox_manager import SandboxManager
sandbox = SandboxManager()
sandbox.cleanup()
print("tau2 knowledge/gym/sandbox ok")
"""
  result = run(["uv", "run", "python", "-c", code], cwd=tau2_dir)
  if result.returncode == 0:
    print_result("ok", "tau2 tools", result.stdout.strip().splitlines()[-1])
    return True
  print_result("fail", "tau2 tools", result.stderr.strip()[-500:])
  return False


def check_financebench_tools() -> bool:
  env_dir = ROOT / "external" / "tools" / "financebench-tools"
  python = env_dir / ".venv" / "bin" / "python"
  pdf = ROOT / "data" / "raw" / "benchmarks" / "financebench" / "pdfs" / "3M_2018_10K.pdf"
  code = f"""
import pypdf, pdfplumber, pandas, sklearn, rank_bm25, rapidfuzz
reader = pypdf.PdfReader({str(pdf)!r})
print(len(reader.pages))
"""
  result = run([str(python), "-c", code])
  if result.returncode == 0:
    print_result("ok", "FinanceBench tools", f"sample PDF pages={result.stdout.strip()}")
    return True
  print_result("fail", "FinanceBench tools", result.stderr.strip()[-500:])
  return False


def check_tabmwp_tools() -> bool:
  env_dir = ROOT / "external" / "tools" / "tabmwp-tools"
  python = env_dir / ".venv" / "bin" / "python"
  code = "import pandas, numpy, sympy, rapidfuzz; print('imports ok')"
  result = run([str(python), "-c", code])
  if result.returncode == 0:
    print_result("ok", "TabMWP tools", result.stdout.strip())
    return True
  print_result("fail", "TabMWP tools", result.stderr.strip()[-500:])
  return False


def check_browsergym_tools() -> bool:
  env_dir = ROOT / "external" / "tools" / "browsergym-agentlab"
  python = env_dir / ".venv" / "bin" / "python"
  nltk_data = env_dir / "nltk_data"
  code = """
import gymnasium as gym
import browsergym.core
import browsergym.webarena
import agentlab
import nltk
nltk.data.find("tokenizers/punkt")
nltk.data.find("tokenizers/punkt_tab")
ids = [id for id in gym.envs.registry.keys() if id.startswith("browsergym/webarena")]
print(len(ids))
"""
  result = run([str(python), "-c", code], env={"NLTK_DATA": str(nltk_data)})
  if result.returncode == 0:
    print_result("ok", "BrowserGym/AgentLab tools", f"webarena_tasks={result.stdout.strip()}")
    return True
  print_result("fail", "BrowserGym/AgentLab tools", result.stderr.strip()[-500:])
  return False


def check_webarena_official_sites() -> bool:
  expected_containers = ["shopping", "shopping_admin", "forum", "gitlab", "wikipedia"]
  result = run(["docker", "ps", "--format", "{{.Names}}"])
  if result.returncode != 0:
    print_result("fail", "WebArena Docker sites", result.stderr.strip()[-500:])
    return False
  running = set(result.stdout.splitlines())
  missing = [name for name in expected_containers if name not in running]
  if missing:
    print_result("pending", "WebArena Docker sites", f"not running: {', '.join(missing)}")
    return False
  print_result("ok", "WebArena Docker sites", "official site containers running")
  return True


def check_api_keys() -> bool:
  optional_keys = ["OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"]
  any_present = False
  for key in optional_keys:
    if os.environ.get(key):
      print_result("ok", f"API key {key}", "present")
      any_present = True
    else:
      print_result("pending", f"API key {key}", "not set in current shell")
  return any_present


def write_report(results: dict[str, bool]) -> None:
  report_dir = ROOT / "outputs" / "benchmarks"
  report_dir.mkdir(parents=True, exist_ok=True)
  report = {
    "results": results,
    "notes": {
      "webarena_official_sites": "Requires large Docker/AMI website deployment; BrowserGym/AgentLab package tooling can be ready before sites are running.",
      "api_keys": "Model-backed evaluations and dense embedding/reranker paths need provider keys in the runtime shell or env file.",
    },
  }
  (report_dir / "tool_readiness.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
  results = {
    "system_tools": check_system_tools(),
    "tau2_tools": check_tau2_tools(),
    "financebench_tools": check_financebench_tools(),
    "tabmwp_tools": check_tabmwp_tools(),
    "browsergym_agentlab_tools": check_browsergym_tools(),
    "webarena_official_sites": check_webarena_official_sites(),
    "api_keys_present": check_api_keys(),
  }
  write_report(results)

  # Missing WebArena sites and API keys are expected pending items, not local
  # installation failures. Return nonzero only when installable local tools fail.
  required = [
    "system_tools",
    "tau2_tools",
    "financebench_tools",
    "tabmwp_tools",
    "browsergym_agentlab_tools",
  ]
  return 0 if all(results[name] for name in required) else 1


if __name__ == "__main__":
  sys.exit(main())
