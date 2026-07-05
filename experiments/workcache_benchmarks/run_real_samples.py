#!/usr/bin/env python3
"""Run small real provider-backed samples for the local WorkCache benchmarks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metrics import build_tables
from protocol import (
  ALL_METHODS,
  BENCHMARK_TASK_FILES,
  REQUIRED_TRACE_FILES,
  ROOT,
  TABLE1_METHODS,
  TABLE2_METHODS,
  TABLE3_METHODS,
  TRACE_SCHEMA_VERSION,
  MethodSpec,
)


PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-v4-pro"
HYPHA_ROOT = (ROOT / "hypha").resolve()
HYPHA_WORKCACHE_BRIDGE = ROOT / "experiments" / "workcache_benchmarks" / "hypha_workcache_bridge.js"
TAU2_BENCH_ROOT = ROOT / "external" / "benchmarks" / "tau2-bench"
TAU2_PYTHON = TAU2_BENCH_ROOT / ".venv" / "bin" / "python"
TAU2_OFFICIAL_RUNNER = ROOT / "experiments" / "workcache_benchmarks" / "tau2_official_runner.py"
HYPHA_WORKCACHE_TREES = (
  "PlanTree",
  "ComputationTree",
  "ToolTree",
  "ObservationTree",
  "VerificationTree",
  "MemoryTree",
  "PromptPrefixTree",
)

# DeepSeek official pricing page for deepseek-v4-pro, USD per 1M tokens.
# See config.json in each run for the source URL and retrieval date.
DEEPSEEK_V4_PRO_CACHE_HIT_INPUT_PER_1M = 0.003625
DEEPSEEK_V4_PRO_CACHE_MISS_INPUT_PER_1M = 0.435
DEEPSEEK_V4_PRO_OUTPUT_PER_1M = 0.87

STOPWORDS = {
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "based",
  "be",
  "by",
  "for",
  "from",
  "give",
  "in",
  "is",
  "it",
  "of",
  "on",
  "or",
  "primarily",
  "question",
  "shown",
  "that",
  "the",
  "to",
  "using",
  "was",
  "what",
  "which",
  "with",
  "year",
}


def stable_hash(value: Any) -> str:
  return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def slug(value: str) -> str:
  return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value)).strip("_")


def task_run_id(
  exp_id: str,
  method: MethodSpec,
  benchmark: str,
  task: dict[str, Any],
  repeat_index: int,
  repeat_count: int,
) -> str:
  pass_suffix = f":pass_{repeat_index + 1}" if repeat_count > 1 else ""
  return f"{exp_id}:{slug(method.name)}:{benchmark}{pass_suffix}:{slug(task['task_id'])}"


def utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


@contextmanager
def hard_timeout(seconds: int):
  if seconds <= 0:
    yield
    return

  def raise_timeout(_signum: int, _frame: Any) -> None:
    raise TimeoutError(f"provider request exceeded {seconds}s")

  previous_handler = signal.getsignal(signal.SIGALRM)
  signal.signal(signal.SIGALRM, raise_timeout)
  previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
  try:
    yield
  finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, previous_handler)
    if previous_timer[0] > 0:
      signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def load_dotenv(path: Path) -> None:
  if not path.exists():
    return
  for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip("\"'")
    os.environ.setdefault(key, value)


def read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  with path.open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        rows.append(json.loads(line))
      if len(rows) >= limit:
        break
  return rows


def write_json(path: Path, data: Any) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as handle:
    for row in rows:
      handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  if not rows:
    path.write_text("", encoding="utf-8")
    return
  columns = list(rows[0])
  with path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns)
    writer.writeheader()
    for row in rows:
      writer.writerow(row)


def prepare_run_dir(run_dir: Path) -> None:
  for rel_path in REQUIRED_TRACE_FILES:
    path = run_dir / rel_path
    if rel_path.endswith(".jsonl"):
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text("", encoding="utf-8")
  for rel_dir in (
    "derived",
    "payloads/llm_responses",
    "payloads/tool_outputs",
    "prompts/prompt_texts",
  ):
    (run_dir / rel_dir).mkdir(parents=True, exist_ok=True)


def unique_methods(methods: list[MethodSpec] | tuple[MethodSpec, ...]) -> list[MethodSpec]:
  seen: set[str] = set()
  selected: list[MethodSpec] = []
  for method in methods:
    if method.name in seen:
      continue
    seen.add(method.name)
    selected.append(method)
  return selected


def select_methods(suite: str) -> list[MethodSpec]:
  suites = {
    "main": unique_methods(TABLE1_METHODS),
    "table1": unique_methods(TABLE1_METHODS),
    "ablation": unique_methods(TABLE2_METHODS),
    "table2": unique_methods(TABLE2_METHODS),
    "mechanism": unique_methods(TABLE3_METHODS),
    "table3": unique_methods(TABLE3_METHODS),
    "all": unique_methods(ALL_METHODS),
  }
  if suite not in suites:
    raise ValueError(f"unknown method suite {suite!r}; expected one of {', '.join(sorted(suites))}")
  return suites[suite]


def hypha_commit() -> str | None:
  for candidate in (ROOT / "hypha", ROOT.parent / "Hypha"):
    if candidate.exists():
      try:
        return subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True).strip()
      except Exception:
        return None
  return None


def provider_cost(usage: dict[str, Any]) -> float:
  prompt_tokens = int(usage.get("prompt_tokens") or 0)
  cache_hit = int(usage.get("prompt_cache_hit_tokens") or 0)
  cache_miss = int(usage.get("prompt_cache_miss_tokens") or max(0, prompt_tokens - cache_hit))
  output_tokens = int(usage.get("completion_tokens") or 0)
  return (
    cache_hit * DEEPSEEK_V4_PRO_CACHE_HIT_INPUT_PER_1M
    + cache_miss * DEEPSEEK_V4_PRO_CACHE_MISS_INPUT_PER_1M
    + output_tokens * DEEPSEEK_V4_PRO_OUTPUT_PER_1M
  ) / 1_000_000


def hypha_workcache_policy(method: MethodSpec) -> dict[str, Any]:
  trees = {
    tree_type: {"enabled": False}
    for tree_type in HYPHA_WORKCACHE_TREES
  }
  for tree_type in (
    "PlanTree",
    "ComputationTree",
    "ToolTree",
    "ObservationTree",
    "VerificationTree",
    "PromptPrefixTree",
  ):
    trees[tree_type] = {"enabled": bool(method.cache_config.get(tree_type, False))}
  return {
    "enabled": any(tree["enabled"] for tree in trees.values()),
    "store": "sqlite",
    "promptBudgetTokens": 4096,
    "unknownEventPolicy": "ignore",
    "allowExtensionEvents": False,
    "trees": trees,
  }


def run_hypha_workcache_bridge(payload: dict[str, Any]) -> dict[str, Any]:
  full_payload = {
    "hyphaRoot": str(HYPHA_ROOT),
    **payload,
  }
  result = subprocess.run(
    ["node", str(HYPHA_WORKCACHE_BRIDGE)],
    input=json.dumps(full_payload, ensure_ascii=False),
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(ROOT),
    check=False,
  )
  if result.returncode != 0:
    raise RuntimeError(f"Hypha WorkCache bridge failed: {result.stderr.strip()}")
  return json.loads(result.stdout)


def hypha_stable_hash(value: Any) -> str:
  result = run_hypha_workcache_bridge(
    {
      "storeKind": "memory",
      "operations": [{"op": "hashStableJson", "input": value}],
    }
  )
  return result["results"][0]["hash"]


class HyphaWorkCacheSession:
  """Thin adapter around Hypha cache-base WorkCacheManager."""

  def __init__(self, method: MethodSpec, benchmark: str, run_dir: Path):
    self.method = method
    self.benchmark = benchmark
    self.policy = hypha_workcache_policy(method)
    self.sqlite_path = (
      run_dir
      / "cache"
      / "hypha"
      / slug(method.name)
      / f"{slug(benchmark)}.sqlite"
    )
    self.events: list[dict[str, Any]] = []
    self.audit_events: list[dict[str, Any]] = []

  @property
  def scope_id(self) -> str:
    return f"{slug(self.method.name)}::{self.benchmark}"

  def enabled(self, tree_type: str) -> bool:
    return bool(self.policy.get("enabled")) and bool(
      self.policy.get("trees", {}).get(tree_type, {}).get("enabled")
    )

  def bridge(self, operations: list[dict[str, Any]], *, store_kind: str = "sqlite") -> dict[str, Any]:
    return run_hypha_workcache_bridge(
      {
        "storeKind": store_kind,
        "sqlitePath": str(self.sqlite_path),
        "policy": self.policy,
        "operations": operations,
      }
    )

  def lookup(self, tree_type: str, node_type: str, identity: Any) -> dict[str, Any]:
    if not self.enabled(tree_type):
      return {"hit": False, "reason": "disabled"}
    result = self.bridge(
      [
        {
          "op": "lookup",
          "query": {
            "treeType": tree_type,
            "nodeType": node_type,
            "identity": identity,
          },
        }
      ]
    )
    return result["results"][0]["lookup"]

  def event(
    self,
    *,
    run_id: str,
    event_id: str,
    event_type: str,
    payload: Any,
    step_id: str | None = None,
    agent_id: str | None = None,
    timestamp: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    return {
      "id": event_id,
      "type": event_type,
      "runId": run_id,
      "sessionId": f"workgraph:{self.scope_id}",
      "stepId": step_id,
      "agentId": agent_id,
      "timestamp": timestamp or utc_now(),
      "payload": payload,
      "metadata": {
        "benchmark": self.benchmark,
        "method": self.method.name,
        "cacheScope": self.scope_id,
        **(metadata or {}),
      },
    }

  def ingest(self, event: dict[str, Any]) -> list[dict[str, Any]]:
    self.events.append(event)
    if not self.policy.get("enabled"):
      return []
    started = time.perf_counter()
    result = self.bridge([{"op": "ingest", "events": [event]}])
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    event.setdefault("metadata", {})["workcacheBridgeLatencyMs"] = latency_ms
    audit_events = result["results"][0]["auditEvents"]
    per_event_latency_ms = latency_ms / max(1, len(audit_events))
    for audit_event in audit_events:
      metadata = audit_event.setdefault("metadata", {})
      metadata["bridgeLatencyMs"] = round(per_event_latency_ms, 3)
    self.audit_events.extend(audit_events)
    return audit_events

  def replay_snapshot(self) -> dict[str, Any]:
    if not self.policy.get("enabled"):
      return {"auditEvents": [], "blocks": {}, "graphs": {}, "demandSignals": []}
    result = run_hypha_workcache_bridge(
      {
        "storeKind": "memory",
        "policy": self.policy,
        "operations": [
          {"op": "ingest", "events": self.events},
          {
            "op": "snapshot",
            "treeTypes": list(HYPHA_WORKCACHE_TREES),
            "runIds": sorted({event["runId"] for event in self.events}),
          },
        ],
      }
    )
    return {
      "auditEvents": result["results"][0]["auditEvents"],
      **result["results"][1],
    }


class DeepSeekClient:
  def __init__(
    self,
    model: str,
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: int = 180,
    max_retries: int = 2,
    retry_backoff_seconds: float = 2.0,
  ):
    self.model = model
    self.base_url = base_url.rstrip("/")
    self.api_key = api_key
    self.timeout_seconds = timeout_seconds
    self.max_retries = max_retries
    self.retry_backoff_seconds = retry_backoff_seconds

  def request_payload(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    response_json: bool = True,
    temperature: float = 0.0,
  ) -> dict[str, Any]:
    payload: dict[str, Any] = {
      "model": self.model,
      "messages": messages,
      "temperature": temperature,
      "max_tokens": max_tokens,
    }
    if response_json:
      payload["response_format"] = {"type": "json_object"}
    return payload

  def chat(
    self,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    response_json: bool = True,
    temperature: float = 0.0,
  ) -> dict[str, Any]:
    url = f"{self.base_url}/chat/completions"
    payload = self.request_payload(
      messages,
      max_tokens=max_tokens,
      response_json=response_json,
      temperature=temperature,
    )

    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    response_data: dict[str, Any] | None = None
    encoded_payload = json.dumps(payload).encode("utf-8")
    for attempt_index in range(self.max_retries + 1):
      attempt_started = time.perf_counter()
      request = urllib.request.Request(url, method="POST")
      request.add_header("Authorization", f"Bearer {self.api_key}")
      request.add_header("Content-Type", "application/json")
      try:
        with hard_timeout(self.timeout_seconds):
          with urllib.request.urlopen(
            request,
            data=encoded_payload,
            timeout=self.timeout_seconds,
          ) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        attempts.append(
          {
            "attempt": attempt_index + 1,
            "ok": True,
            "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
          }
        )
        break
      except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
        attempts.append(
          {
            "attempt": attempt_index + 1,
            "ok": False,
            "error_type": type(exc).__name__,
            "error_message": f"provider HTTP {exc.code}: {body[:500]}",
            "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
            "retryable": retryable,
          }
        )
        if not retryable or attempt_index >= self.max_retries:
          raise RuntimeError(f"provider HTTP {exc.code}: {body[:500]}") from exc
      except (
        TimeoutError,
        urllib.error.URLError,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
        ConnectionError,
        OSError,
      ) as exc:
        attempts.append(
          {
            "attempt": attempt_index + 1,
            "ok": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "latency_ms": round((time.perf_counter() - attempt_started) * 1000, 2),
            "retryable": True,
          }
        )
        if attempt_index >= self.max_retries:
          raise RuntimeError(
            f"provider request failed after {len(attempts)} attempt(s): "
            f"{type(exc).__name__}: {str(exc)[:500]}"
          ) from exc
      sleep_seconds = self.retry_backoff_seconds * (2**attempt_index)
      time.sleep(sleep_seconds)
    if response_data is None:
      raise RuntimeError("provider request failed without response data")
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    choice = response_data["choices"][0]
    message = choice.get("message", {})
    usage = response_data.get("usage", {})
    return {
      "content": message.get("content") or "",
      "reasoning_content": message.get("reasoning_content") or "",
      "finish_reason": choice.get("finish_reason"),
      "latency_ms": latency_ms,
      "usage": usage,
      "cost_usd": provider_cost(usage),
      "raw": response_data,
      "attempts": attempts,
      "request": payload,
    }


def computation_identity(client: DeepSeekClient, request_payload: dict[str, Any]) -> dict[str, Any]:
  params = {
    "temperature": request_payload.get("temperature"),
    "max_tokens": request_payload.get("max_tokens"),
    "response_format": request_payload.get("response_format"),
  }
  return {
    "sourceEventType": "model.call.completed",
    "provider": PROVIDER,
    "model": client.model,
    "requestHash": stable_hash(request_payload),
    "paramsHash": stable_hash(params),
    "environmentHash": stable_hash({"provider": PROVIDER, "base_url": client.base_url}),
  }


def computation_payload(
  client: DeepSeekClient,
  request_payload: dict[str, Any],
  response: dict[str, Any],
) -> dict[str, Any]:
  identity = computation_identity(client, request_payload)
  return {
    "provider": identity["provider"],
    "model": identity["model"],
    "requestHash": identity["requestHash"],
    "paramsHash": identity["paramsHash"],
    "envHash": identity["environmentHash"],
    "output": {
      "content": response.get("content") or "",
      "reasoningContent": response.get("reasoning_content") or "",
      "rawResponseHash": stable_hash(response.get("raw")),
    },
    "usage": response.get("usage") or {},
    "finishReason": response.get("finish_reason"),
    "latencyMs": response.get("latency_ms"),
    "cacheReuse": bool((response.get("raw") or {}).get("cacheReuse")),
    "validity": {
      "status": "valid",
      "sourceHashes": {
        "request": identity["requestHash"],
        "params": identity["paramsHash"],
        "environment": identity["environmentHash"],
      },
    },
  }


def cached_response_from_computation(
  lookup: dict[str, Any],
  request_payload: dict[str, Any],
) -> dict[str, Any]:
  block = lookup.get("block", {})
  value = block.get("value", {})
  output = value.get("output") or {}
  return {
    "content": output.get("content") or "",
    "reasoning_content": output.get("reasoningContent") or "",
    "finish_reason": value.get("finishReason"),
    "latency_ms": 0,
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "prompt_cache_hit_tokens": 0},
    "cost_usd": 0.0,
    "attempts": [],
    "raw": {
      "cached_from_workcache": True,
      "block_id": block.get("id"),
      "source_event_id": block.get("sourceEventId"),
      "cached_usage": value.get("usage"),
      "raw_response_hash": output.get("rawResponseHash"),
    },
    "request": request_payload,
  }


def model_call_lookup(cache: HyphaWorkCacheSession, client: DeepSeekClient, request_payload: dict[str, Any]) -> dict[str, Any]:
  return cache.lookup("ComputationTree", "computation", computation_identity(client, request_payload))


def workcache_lookup_status(lookup: dict[str, Any], executed: bool) -> str:
  if lookup.get("hit"):
    return "hit"
  if lookup.get("reason") == "disabled":
    return "disabled"
  return "miss" if executed else "bypass"


def ingest_model_call(
  cache: HyphaWorkCacheSession,
  *,
  run_id: str,
  benchmark: str,
  client: DeepSeekClient,
  request_payload: dict[str, Any],
  response: dict[str, Any],
  step_id: str,
) -> None:
  cache.ingest(
    cache.event(
      run_id=run_id,
      event_id=f"{run_id}:model.call.completed:{step_id}",
      event_type="model.call.completed",
      step_id=step_id,
      agent_id=f"agent.{benchmark}.deepseek_pro",
      payload=computation_payload(client, request_payload, response),
    )
  )


def extract_json(text: str) -> dict[str, Any]:
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
      try:
        return json.loads(match.group(0))
      except json.JSONDecodeError:
        pass
  return {"answer": text.strip(), "parse_error": True}


def prompt_text(name: str) -> str:
  return (ROOT / "experiments" / "workcache_benchmarks" / "prompts" / name).read_text(
    encoding="utf-8"
  )


def finance_query_terms(question: str) -> list[str]:
  terms = [term for term in re.findall(r"[a-zA-Z0-9]+", question.lower()) if len(term) > 2]
  lowered = question.lower()
  if "capital expenditure" in lowered or "capex" in lowered:
    terms.extend(["capital", "expenditure", "purchases", "property", "plant", "equipment", "ppe", "investing"])
  if "net ppne" in lowered or "ppne" in lowered:
    terms.extend(["property", "plant", "equipment", "net", "ppne", "balance", "sheet"])
  if "capital-intensive" in lowered or "capital intensive" in lowered:
    terms.extend(["capex", "capital", "expenditure", "fixed", "assets", "total", "assets", "sales", "revenue"])
  return [term for term in terms if term not in STOPWORDS]


def extract_pdf_pages(pdf_path: Path) -> list[str]:
  output = subprocess.check_output(["pdftotext", "-layout", str(pdf_path), "-"], text=True, errors="replace")
  pages = output.split("\f")
  return [page.strip() for page in pages if page.strip()]


def retrieve_finance_pages(
  task: dict[str, Any],
  top_k: int,
  *,
  pages: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  input_data = task["input"]
  pdf_path = ROOT / input_data["document"]["pdf_path"]
  if pages is None:
    pages = extract_pdf_pages(pdf_path)
  terms = finance_query_terms(input_data["question"])
  scored: list[tuple[float, int, str]] = []
  for page_index, page_text in enumerate(pages, start=1):
    lowered = page_text.lower()
    score = 0.0
    for term in terms:
      score += lowered.count(term)
    year = str(input_data["document"].get("doc_period") or "")
    if year and year in page_text:
      score += 2.0
    scored.append((score, page_index, page_text))
  scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
  selected = [
    {
      "page": page_index,
      "score": score,
      "text": page_text[:4500],
      "text_hash": stable_hash(page_text),
    }
    for score, page_index, page_text in scored[:top_k]
  ]
  tool_payload = {
    "pdf_path": str(pdf_path),
    "page_count": len(pages),
    "query_terms": terms,
    "selected_pages": [
      {"page": item["page"], "score": item["score"], "text_hash": item["text_hash"]} for item in selected
    ],
  }
  return selected, tool_payload


def build_finance_prompt(task: dict[str, Any], snippets: list[dict[str, Any]]) -> list[dict[str, str]]:
  input_data = task["input"]
  prompt_payload = {
    "task_id": task["task_id"],
    "company": input_data.get("company"),
    "question": input_data.get("question"),
    "document": {
      key: value
      for key, value in input_data.get("document", {}).items()
      if key != "doc_link"
    },
    "retrieved_snippets": [
      {
        "page": snippet["page"],
        "retrieval_score": snippet["score"],
        "text": snippet["text"],
      }
      for snippet in snippets
    ],
  }
  return [
    {
      "role": "system",
      "content": prompt_text("financebench_agent.md")
      + "\n\nReturn JSON only. Include no markdown. Keep internal reasoning brief and reserve tokens for the final JSON object. The JSON object must follow the output contract.",
    },
    {
      "role": "user",
      "content": "Answer from the retrieved filing snippets only. Do not use any gold answer or gold evidence.\n"
      + json.dumps(prompt_payload, ensure_ascii=False, indent=2),
    },
  ]


def build_tabmwp_prompt(task: dict[str, Any]) -> list[dict[str, str]]:
  input_data = task["input"]
  prompt_payload = {
    "task_id": task["task_id"],
    "table_title": input_data.get("table_title"),
    "table": input_data.get("table"),
    "table_for_pd": input_data.get("table_for_pd"),
    "question": input_data.get("question"),
    "choices": input_data.get("choices"),
    "unit": input_data.get("unit"),
    "metadata": {
      key: task.get("metadata", {}).get(key)
      for key in ("ans_type", "ques_type", "grade", "row_num", "column_num")
    },
  }
  return [
    {
      "role": "system",
      "content": prompt_text("tabmwp_agent.md")
      + "\n\nReturn JSON only. Include no markdown. Keep internal reasoning brief and reserve tokens for the final JSON object. The JSON object must follow the output contract.",
    },
    {
      "role": "user",
      "content": "Solve this TabMWP evaluation item. Do not use gold solution text.\n"
      + json.dumps(prompt_payload, ensure_ascii=False, indent=2),
    },
  ]


def normalize_text(value: Any) -> str:
  text = str(value or "").lower()
  text = text.replace("$", " ").replace(",", "")
  text = re.sub(r"[^a-z0-9.%+-]+", " ", text)
  return " ".join(text.split())


def numbers(value: Any) -> list[float]:
  found: list[float] = []
  for match in re.findall(r"[-+]?\$?\d[\d,]*(?:\.\d+)?%?", str(value or "")):
    raw = match.replace("$", "").replace(",", "")
    is_percent = raw.endswith("%")
    raw = raw.rstrip("%")
    try:
      number = float(raw)
      found.append(number / 100 if is_percent else number)
    except ValueError:
      continue
  return found


def numeric_close(predicted: float, gold: float) -> bool:
  if abs(predicted - gold) <= 1e-6:
    return True
  scale = max(1.0, abs(gold))
  if abs(predicted - gold) / scale <= 0.02:
    return True
  if abs(predicted / 1000 - gold) / scale <= 0.02:
    return True
  if abs(predicted - gold / 1000) / max(1.0, abs(gold / 1000)) <= 0.02:
    return True
  return False


def score_answer(benchmark: str, prediction: dict[str, Any], gold: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
  predicted_answer = prediction.get("answer") or prediction.get("response") or ""
  gold_answer = gold.get("answer", "")
  pred_norm = normalize_text(predicted_answer)
  gold_norm = normalize_text(gold_answer)
  pred_numbers = numbers(predicted_answer)
  gold_numbers = numbers(gold_answer)

  if benchmark == "financebench" and gold_norm.split()[:1] in (["yes"], ["no"]):
    gold_first = gold_norm.split()[0]
    pred_words = pred_norm.split()
    pred_first = pred_words[0] if pred_words else ""
    matched = pred_first == gold_first
    if gold_first == "no" and not matched:
      matched = "not capital intensive" in pred_norm or "not a capital intensive" in pred_norm
    return matched, {
      "scorer": "yes_no_prefix",
      "matched": matched,
      "predicted_normalized": pred_norm,
      "gold_normalized": gold_norm,
    }

  if gold_numbers and pred_numbers:
    matched = any(numeric_close(predicted, gold_value) for predicted in pred_numbers for gold_value in gold_numbers)
    return matched, {
      "scorer": "numeric_tolerance",
      "matched": matched,
      "predicted_numbers": pred_numbers,
      "gold_numbers": gold_numbers,
      "predicted_normalized": pred_norm,
      "gold_normalized": gold_norm,
    }

  matched = bool(gold_norm) and (gold_norm in pred_norm or pred_norm in gold_norm)
  return matched, {
    "scorer": "normalized_containment",
    "matched": matched,
    "predicted_normalized": pred_norm,
    "gold_normalized": gold_norm,
  }


def append_runtime_events(
  records: dict[str, list[dict[str, Any]]],
  run_id: str,
  task: dict[str, Any],
  method: MethodSpec,
  event_type: str,
) -> None:
  records["raw/runtime_events.jsonl"].append(
    {
      "event_id": f"evt:{run_id}:{event_type}",
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": task["benchmark"],
      "method": method.name,
      "timestamp": utc_now(),
      "event_type": event_type,
      "agent_id": f"agent.{task['benchmark']}.deepseek_pro",
      "payload": {"trace_schema_version": TRACE_SCHEMA_VERSION},
    }
  )


def record_prompt(
  records: dict[str, list[dict[str, Any]]],
  run_id: str,
  task: dict[str, Any],
  method: MethodSpec,
  cache: HyphaWorkCacheSession,
  messages: list[dict[str, str]],
) -> str:
  prompt_id = f"prompt:{run_id}"
  prompt_hash = stable_hash(messages)
  prefix_hash = stable_hash(messages[0]["content"])
  prefix_lookup = cache.lookup(
    "PromptPrefixTree",
    "prompt_prefix",
    {
      "prefixHash": prefix_hash,
      "blockId": "system",
      "blockType": "system",
      "blockHash": prefix_hash,
    },
  )
  cache.ingest(
    cache.event(
      run_id=run_id,
      event_id=f"{run_id}:llm.cache.write:{slug(prompt_id)}",
      event_type="llm.cache.write",
      step_id=prompt_id,
      agent_id=f"agent.{task['benchmark']}.deepseek_pro",
      payload={
        "prefixMetadata": {
          "prefixHash": prefix_hash,
          "requestHash": prompt_hash,
          "dynamicSuffixHash": stable_hash(messages[1]["content"] if len(messages) > 1 else ""),
          "blocks": [
            {
              "id": "system",
              "type": "system",
              "hash": prefix_hash,
              "stable": True,
              "content": messages[0]["content"],
              "tokenEstimate": max(1, len(messages[0]["content"]) // 4),
              "order": 0,
              "templateId": f"{task['benchmark']}.system",
              "templateVersion": "1",
              "source": "workgraph.benchmark.prompt",
            }
          ],
        }
      },
      metadata={"prefixMetadata": {"prefixHash": prefix_hash}},
    )
  )
  records["prompts/prompt_assemblies.jsonl"].append(
    {
      "prompt_id": prompt_id,
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": task["benchmark"],
      "method": method.name,
      "stable_prefix_hash": prefix_hash,
      "dynamic_input_hash": stable_hash(messages[1]["content"] if len(messages) > 1 else ""),
      "assembled_prompt_hash": prompt_hash,
      "prefix_cache_status": "hit" if prefix_lookup.get("hit") else prefix_lookup.get("reason", "miss"),
      "blocks": [
        {
          "block_id": f"system:{task['benchmark']}",
          "role": "system",
          "hash": prefix_hash,
          "cache_scope": "stable_prompt_prefix",
        },
        {
          "block_id": f"task:{task['task_id']}",
          "role": "user",
          "hash": stable_hash(messages[1]["content"] if len(messages) > 1 else ""),
          "cache_scope": "dynamic_task_input",
        },
      ],
    }
  )
  return prompt_hash


def append_hypha_cache_snapshot(
  records: dict[str, list[dict[str, Any]]],
  cache: HyphaWorkCacheSession,
  snapshot: dict[str, Any],
) -> None:
  source_events_by_id = {event["id"]: event for event in cache.events}
  for source_event in cache.events:
    records["raw/runtime_events.jsonl"].append(
      {
        "event_id": source_event["id"],
        "run_id": source_event["runId"],
        "task_id": source_event["runId"].split(":")[-1],
        "benchmark": cache.benchmark,
        "method": cache.method.name,
        "timestamp": source_event["timestamp"],
        "event_type": source_event["type"],
        "agent_id": source_event.get("agentId"),
        "payload": source_event.get("payload"),
      }
    )

  audit_events = snapshot.get("auditEvents", [])
  audit_counts_by_source: dict[str, int] = {}
  hit_cache_keys: set[str] = set()
  miss_cache_keys: set[str] = set()
  lookup_cache_keys: set[str] = set()
  for audit_event in audit_events:
    payload = audit_event.get("payload", {})
    source_event_id = str(payload.get("sourceEventId") or "")
    if source_event_id:
      audit_counts_by_source[source_event_id] = audit_counts_by_source.get(source_event_id, 0) + 1
    cache_key = payload.get("cacheKey")
    event_type = audit_event.get("type", "")
    if isinstance(cache_key, str):
      if event_type == "workcache.lookup":
        lookup_cache_keys.add(cache_key)
      elif event_type == "workcache.hit":
        hit_cache_keys.add(cache_key)
      elif event_type == "workcache.miss":
        miss_cache_keys.add(cache_key)

  def audit_latency_ms(audit_event: dict[str, Any]) -> float:
    payload = audit_event.get("payload", {})
    metadata = audit_event.get("metadata", {})
    candidates = [
      metadata.get("bridgeLatencyMs") if isinstance(metadata, dict) else None,
      payload.get("latencyMs") if isinstance(payload, dict) else None,
    ]
    source_event_id = str(payload.get("sourceEventId") or "") if isinstance(payload, dict) else ""
    source_event = source_events_by_id.get(source_event_id)
    if source_event:
      source_metadata = source_event.get("metadata", {})
      source_latency = (
        source_metadata.get("workcacheBridgeLatencyMs")
        if isinstance(source_metadata, dict)
        else None
      )
      if isinstance(source_latency, (int, float)):
        candidates.append(source_latency / max(1, audit_counts_by_source.get(source_event_id, 1)))
    for candidate in candidates:
      if isinstance(candidate, (int, float)):
        return round(float(candidate), 3)
    return 0.0

  for index, audit_event in enumerate(audit_events):
    payload = audit_event.get("payload", {})
    event_type = audit_event.get("type", "")
    result = event_type.replace("workcache.", "")
    if result == "lookup":
      result = "lookup"
    records["raw/runtime_events.jsonl"].append(
      {
        "event_id": f"{audit_event.get('runId')}:hypha:{event_type}:{index}",
        "run_id": audit_event.get("runId"),
        "task_id": str(audit_event.get("runId", "")).split(":")[-1],
        "benchmark": cache.benchmark,
        "method": cache.method.name,
        "timestamp": audit_event.get("timestamp") or utc_now(),
        "event_type": event_type,
        "agent_id": None,
        "payload": payload,
      }
    )
    records["cache/cache_ops.jsonl"].append(
      {
        "cache_op_id": f"{audit_event.get('runId')}:hypha-cache:{index}",
        "run_id": audit_event.get("runId"),
        "task_id": str(audit_event.get("runId", "")).split(":")[-1],
        "benchmark": cache.benchmark,
        "method": cache.method.name,
        "tree_type": payload.get("treeType"),
        "cache_scope": cache.scope_id,
        "key_hash": stable_hash(payload.get("cacheKey")),
        "cache_key": payload.get("cacheKey"),
        "block_id": payload.get("blockId"),
        "result": result,
        "validation_result": "valid" if event_type == "workcache.hit" else payload.get("reason", ""),
        "stale": False,
        "latency_ms": audit_latency_ms(audit_event),
        "source_event_id": payload.get("sourceEventId"),
        "source_event_type": payload.get("sourceEventType"),
      }
    )
    if event_type == "workcache.write":
      records["cache/tree_updates.jsonl"].append(
        {
          "tree_update_id": f"{audit_event.get('runId')}:hypha-tree-write:{index}",
          "run_id": audit_event.get("runId"),
          "task_id": str(audit_event.get("runId", "")).split(":")[-1],
          "benchmark": cache.benchmark,
          "method": cache.method.name,
          "tree_type": payload.get("treeType"),
          "cache_scope": cache.scope_id,
          "key_hash": stable_hash(payload.get("cacheKey")),
          "operation": "write",
        }
      )

  node_run_ids: dict[str, str] = {}
  for run_id, graph in (snapshot.get("graphs") or {}).items():
    if not graph:
      continue
    for node in graph.get("nodes", []):
      node_id = node.get("id") or node.get("nodeId")
      if isinstance(node_id, str):
        node_run_ids[node_id] = str(run_id)
      node_cache_key = node.get("cacheKey")
      if isinstance(node_cache_key, str) and node_cache_key in hit_cache_keys:
        cache_status = "hit"
      elif isinstance(node_cache_key, str) and node_cache_key in miss_cache_keys:
        cache_status = "miss"
      elif node.get("outputBlockIds"):
        cache_status = "materialized"
      else:
        cache_status = "bypass"
      records["graph/work_graph_nodes.jsonl"].append(
        {
          "node_id": node_id,
          "run_id": run_id,
          "task_id": str(run_id).split(":")[-1],
          "benchmark": cache.benchmark,
          "method": cache.method.name,
          "tree_type": node.get("primaryTreeType"),
          "critical_path": bool(node.get("criticality", 0) >= 1 or node.get("status") == "done"),
          "cache_status": cache_status,
          "payload": node,
        }
      )
    for edge in graph.get("edges", []):
      records["graph/work_graph_edges.jsonl"].append(
        {
          "edge_id": edge.get("id") or edge.get("edgeId"),
          "run_id": run_id,
          "task_id": str(run_id).split(":")[-1],
          "benchmark": cache.benchmark,
          "method": cache.method.name,
          "from": edge.get("from"),
          "to": edge.get("to"),
          "edge_type": edge.get("edgeType"),
          "weight": edge.get("weight"),
          "payload": edge,
        }
      )

  for signal in snapshot.get("demandSignals", []):
    source_node_id = str(signal.get("sourceNodeId") or "")
    signal_run_id = node_run_ids.get(source_node_id, "")
    target_key = signal.get("targetKey")
    predicted = bool(cache.method.cache_config.get("WorkGraphDemand", False))
    actual_needed = isinstance(target_key, str) and target_key in lookup_cache_keys
    actual_used = isinstance(target_key, str) and target_key in hit_cache_keys
    records["graph/demand_signals.jsonl"].append(
      {
        "demand_signal_id": signal.get("id") or signal.get("signalId"),
        "run_id": signal_run_id,
        "task_id": str(signal_run_id).split(":")[-1] if signal_run_id else "",
        "benchmark": cache.benchmark,
        "method": cache.method.name,
        "tree_type": signal.get("targetTreeType"),
        "predicted": predicted,
        "actual_needed": actual_needed,
        "actual_used": actual_used,
        "demand_score": signal.get("demandScore"),
        "payload": signal,
      }
    )


def tau2_domain(task: dict[str, Any]) -> str:
  domain = task.get("input", {}).get("domain")
  if domain:
    return str(domain)
  task_id = str(task["task_id"])
  return task_id.split(":", 1)[0] if ":" in task_id else "airline"


def run_tau2_official(
  run_dir: Path,
  run_id: str,
  model: str,
  task: dict[str, Any],
  cache: HyphaWorkCacheSession,
  tau2_timeout: int,
  subprocess_timeout: int,
) -> dict[str, Any]:
  if not TAU2_PYTHON.exists():
    raise RuntimeError(f"tau2 official venv python is missing: {TAU2_PYTHON}")
  output_path = run_dir / "payloads" / "tau2_official" / f"{slug(run_id)}.json"
  save_dir = run_dir / "payloads" / "tau2_official_logs" / slug(run_id)
  result = subprocess.run(
    [
      str(TAU2_PYTHON),
      str(TAU2_OFFICIAL_RUNNER),
      "--domain",
      tau2_domain(task),
      "--task-id",
      str(task["task_id"]),
      "--model",
      model,
      "--output",
      str(output_path),
      "--save-dir",
      str(save_dir),
      "--timeout",
      str(tau2_timeout),
      "--hypha-root",
      str(HYPHA_ROOT),
      "--workcache-bridge",
      str(HYPHA_WORKCACHE_BRIDGE),
      "--workcache-sqlite",
      str(cache.sqlite_path),
      "--workcache-policy-json",
      json.dumps(cache.policy, ensure_ascii=False),
      "--workcache-run-id",
      run_id,
      "--cache-scope",
      cache.scope_id,
    ],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(ROOT),
    timeout=subprocess_timeout,
    check=False,
  )
  if result.returncode != 0:
    raise RuntimeError(
      "Official tau2 runner failed; no fallback score will be used.\n"
      f"stdout:\n{result.stdout[-4000:]}\n"
      f"stderr:\n{result.stderr[-4000:]}"
    )
  payload = json.loads(output_path.read_text(encoding="utf-8"))
  reward_info = payload.get("simulation", {}).get("reward_info")
  if reward_info is None or "reward" not in reward_info:
    raise RuntimeError(f"Official tau2 runner returned no reward_info: {output_path}")
  return payload


def tau2_agent_usage(tau2_payload: dict[str, Any]) -> dict[str, Any]:
  prompt_tokens = 0
  completion_tokens = 0
  for message in tau2_payload.get("simulation", {}).get("messages", []):
    if message.get("role") != "assistant":
      continue
    usage = message.get("usage") or {}
    prompt_tokens += int(usage.get("prompt_tokens") or 0)
    completion_tokens += int(usage.get("completion_tokens") or 0)
  simulation = tau2_payload.get("simulation", {})
  return {
    "prompt_tokens": prompt_tokens,
    "completion_tokens": completion_tokens,
    "agent_cost_usd": float(simulation.get("agent_cost") or 0),
    "user_cost_usd": float(simulation.get("user_cost") or 0),
  }


def append_tau2_official_trace(
  records: dict[str, list[dict[str, Any]]],
  run_dir: Path,
  run_id: str,
  task: dict[str, Any],
  method: MethodSpec,
  cache: HyphaWorkCacheSession,
  tau2_payload: dict[str, Any],
) -> None:
  simulation = tau2_payload["simulation"]
  for source_event in simulation.get("workcache_source_events", []):
    cache.events.append(source_event)

  messages = simulation.get("messages", [])
  agent_model_events = [
    event
    for event in simulation.get("workcache_source_events", [])
    if event.get("type") == "model.call.completed" and event.get("stepId") == "agent_response"
  ]
  agent_model_event_index = 0
  for index, message in enumerate(messages):
    role = message.get("role")
    if role not in {"assistant", "user", "tool"}:
      continue
    records["raw/runtime_events.jsonl"].append(
      {
        "event_id": f"{run_id}:tau2.message:{index}",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": task["benchmark"],
        "method": method.name,
        "timestamp": message.get("timestamp") or utc_now(),
        "event_type": f"tau2.message.{role}",
        "agent_id": f"agent.{task['benchmark']}.deepseek_pro" if role == "assistant" else None,
        "payload": message,
      }
    )
    if role == "assistant":
      usage = message.get("usage") or {}
      has_provider_usage = bool(usage) or bool(message.get("cost")) or message.get("generation_time_seconds") is not None
      model_event: dict[str, Any] | None = None
      if has_provider_usage or int(message.get("turn_idx") or 0) > 0:
        if agent_model_event_index < len(agent_model_events):
          model_event = agent_model_events[agent_model_event_index]
          agent_model_event_index += 1
      cache_reuse = bool((model_event or {}).get("payload", {}).get("cacheReuse"))
      executed = (not cache_reuse) if model_event is not None else has_provider_usage
      workcache_status = (
        "hit"
        if cache_reuse
        else "miss"
        if model_event is not None
        else "disabled"
        if not cache.enabled("ComputationTree")
        else "not_applicable"
      )
      records["raw/llm_calls.jsonl"].append(
        {
          "call_id": f"llm:{run_id}:tau2_agent:{index}",
          "run_id": run_id,
          "task_id": task["task_id"],
          "benchmark": task["benchmark"],
          "method": method.name,
          "provider": PROVIDER,
          "model": tau2_payload.get("model"),
          "purpose": "tau2_official_agent_turn",
          "executed": executed,
          "input_tokens": int(usage.get("prompt_tokens") or 0),
          "output_tokens": int(usage.get("completion_tokens") or 0),
          "cached_input_tokens": 0,
          "cost_usd": float(message.get("cost") or 0),
          "latency_ms": round(float(message.get("generation_time_seconds") or 0) * 1000, 2),
          "prefix_hash": "",
          "finish_reason": "",
          "response_path": str(
            (Path("payloads") / "tau2_official" / f"{slug(run_id)}.json")
          ),
          "workcache_status": workcache_status,
        }
      )
    for tool_call in message.get("tool_calls") or []:
      tool_identity = {
        "toolId": tool_call.get("name"),
        "stableArgs": tool_call.get("arguments"),
        "permissionScope": ["tau2.domain_tool"],
      }
      cache.lookup("ToolTree", "tool", tool_identity)
      cache.ingest(
        cache.event(
          run_id=run_id,
          event_id=f"{run_id}:tool.call.completed:tau2:{index}:{slug(tool_call.get('id') or tool_call.get('name') or str(index))}",
          event_type="tool.call.completed",
          step_id=f"tau2_tool_{index}",
          agent_id=f"agent.{task['benchmark']}.deepseek_pro",
          payload={
            "toolId": tool_identity["toolId"],
            "sideEffectLevel": "read",
            "stableArgs": tool_identity["stableArgs"],
            "permissionScope": tool_identity["permissionScope"],
            "output": {"message_index": index, "requestor": tool_call.get("requestor")},
            "validity": {
              "status": "valid",
              "sourceHashes": {"tau2_message": stable_hash(message)},
            },
            "source": "tau2.official_simulation",
          },
        )
      )

  for log_file in simulation.get("llm_log_files", []):
    try:
      log_payload = json.loads(Path(log_file).read_text(encoding="utf-8"))
    except Exception:
      continue
    request_messages = log_payload.get("request", {}).get("messages") or []
    if log_payload.get("call_name") != "agent_response" or not request_messages:
      continue
    system_content = str(request_messages[0].get("content") or "")
    if not system_content:
      continue
    prefix_hash = stable_hash(system_content)
    prefix_lookup = cache.lookup(
      "PromptPrefixTree",
      "prompt_prefix",
      {
        "prefixHash": prefix_hash,
        "blockId": "tau2_agent_system",
        "blockType": "system",
        "blockHash": prefix_hash,
      },
    )
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:llm.cache.write:tau2_agent_system:{stable_hash(log_file)[:12]}",
        event_type="llm.cache.write",
        step_id="tau2_agent_prompt",
        agent_id=f"agent.{task['benchmark']}.deepseek_pro",
        payload={
          "prefixMetadata": {
            "prefixHash": prefix_hash,
            "requestHash": stable_hash(log_payload.get("request")),
            "dynamicSuffixHash": stable_hash(request_messages[1:]),
            "blocks": [
              {
                "id": "tau2_agent_system",
                "type": "system",
                "hash": prefix_hash,
                "stable": True,
                "content": system_content,
                "tokenEstimate": max(1, len(system_content) // 4),
                "order": 0,
                "templateId": "tau2.official.llm_agent.system",
                "templateVersion": "upstream",
                "source": "tau2.official.llm_debug",
              }
            ],
          }
        },
        metadata={"prefixMetadata": {"prefixHash": prefix_hash}},
      )
    )
    records["prompts/prompt_assemblies.jsonl"].append(
      {
        "prompt_id": f"prompt:{run_id}:tau2_official:{stable_hash(log_file)[:12]}",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": task["benchmark"],
        "method": method.name,
        "stable_prefix_hash": prefix_hash,
        "dynamic_input_hash": stable_hash(request_messages[1:]),
        "assembled_prompt_hash": stable_hash(log_payload.get("request")),
        "prefix_cache_status": "hit" if prefix_lookup.get("hit") else prefix_lookup.get("reason", "miss"),
        "blocks": [
          {
            "block_id": "tau2_agent_system",
            "role": "system",
            "hash": prefix_hash,
            "cache_scope": "tau2_official_agent_prompt",
          }
        ],
      }
    )


def run_task(
  client: DeepSeekClient,
  records: dict[str, list[dict[str, Any]]],
  run_dir: Path,
  exp_id: str,
  method: MethodSpec,
  cache: HyphaWorkCacheSession,
  benchmark: str,
  task: dict[str, Any],
  finance_top_k: int,
  repeat_index: int = 0,
  repeat_count: int = 1,
  tau2_timeout: int = 300,
  tau2_subprocess_timeout: int = 420,
) -> dict[str, Any]:
  run_id = task_run_id(exp_id, method, benchmark, task, repeat_index, repeat_count)
  append_runtime_events(records, run_id, task, method, "agent.run.started")
  started = time.perf_counter()

  tool_payload: dict[str, Any] | None = None
  plan_key = {
    "benchmark": benchmark,
    "domain": task["input"].get("domain"),
    "question_type": task.get("metadata", {}).get("question_type") or task.get("metadata", {}).get("ques_type"),
    "answer_type": task.get("metadata", {}).get("ans_type"),
  }
  plan_payload = {
    "operation": "benchmark_agent_flow_plan",
    "plan": plan_key,
    "recomputeCost": 1,
  }
  if cache.enabled("PlanTree"):
    cache.lookup(
      "PlanTree",
      "plan",
      {
        "sourceEventType": "agent.reasoning.completed",
        "payloadHash": hypha_stable_hash(plan_payload),
      },
    )
  cache.ingest(
    cache.event(
      run_id=run_id,
      event_id=f"{run_id}:agent.reasoning.completed:plan",
      event_type="agent.reasoning.completed",
      step_id="plan",
      agent_id=f"agent.{benchmark}.deepseek_pro",
      payload=plan_payload,
    )
  )

  if benchmark == "financebench":
    input_data = task["input"]
    pdf_path = ROOT / input_data["document"]["pdf_path"]
    pdf_identity = {
      "toolId": "pdftotext_fixed_retrieval.extract_pages",
      "stableArgs": {"pdf_path": str(pdf_path), "doc_name": input_data["document"].get("doc_name")},
      "permissionScope": ["file.read", "pdf.extract"],
    }
    pdf_lookup = cache.lookup(
      "ToolTree",
      "tool",
      pdf_identity,
    )
    if pdf_lookup.get("hit") and isinstance(pdf_lookup.get("block", {}).get("value", {}).get("output"), list):
      pages = pdf_lookup["block"]["value"]["output"]
      pdf_executed = False
      pdf_cache_status = "hit"
    else:
      pages = extract_pdf_pages(pdf_path)
      pdf_executed = True
      pdf_cache_status = pdf_lookup.get("reason", "miss")
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:tool.call.completed:pdf_pages",
        event_type="tool.call.completed",
        step_id="pdf_pages",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "toolId": pdf_identity["toolId"],
          "sideEffectLevel": "read",
          "stableArgs": pdf_identity["stableArgs"],
          "permissionScope": pdf_identity["permissionScope"],
          "output": pages,
          "validity": {
            "status": "valid",
            "sourceHashes": {str(pdf_path): stable_hash({"path": str(pdf_path), "pages": len(pages)})},
          },
          "source": "workgraph.benchmark",
          "cacheReuse": pdf_cache_status == "hit",
        },
      )
    )

    snippets, tool_payload = retrieve_finance_pages(task, finance_top_k, pages=pages)
    messages = build_finance_prompt(task, snippets)
    records["raw/tool_calls.jsonl"].append(
      {
        "tool_call_id": f"tool:{run_id}:pdf_retrieval",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "tool_name": "pdftotext_fixed_retrieval",
        "executed": pdf_executed,
        "cache_status": pdf_cache_status,
        "latency_ms": 0,
        "input_hash": stable_hash(task["input"]),
        "output_hash": stable_hash(tool_payload),
      }
    )
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:context.build.completed:retrieved_pages",
        event_type="context.build.completed",
        step_id="retrieved_pages",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "resourceId": f"financebench:{task['task_id']}:retrieved_pages",
          "output": tool_payload,
          "contentHash": stable_hash(tool_payload),
          "provenance": {
            "resourceId": f"financebench:{task['task_id']}:retrieved_pages",
            "sourceHash": stable_hash(task["input"]),
          },
        },
      )
    )
    records["raw/observations.jsonl"].append(
      {
        "observation_id": f"obs:{run_id}:retrieved_pages",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "source": "finance_pdf_retrieval",
        "cache_status": "source_event_ingested",
        "payload": tool_payload,
      }
    )
    write_json(run_dir / "payloads" / "tool_outputs" / f"{slug(run_id)}_retrieval.json", tool_payload)
  elif benchmark == "promptpg-tabmwp":
    messages = build_tabmwp_prompt(task)
    table_for_pd = task["input"].get("table_for_pd") or {}
    table_identity = {
      "toolId": "tabmwp_table_parser",
      "stableArgs": {"table_hash": stable_hash(task["input"].get("table"))},
      "permissionScope": ["table.parse"],
    }
    table_lookup = cache.lookup(
      "ToolTree",
      "tool",
      table_identity,
    )
    table_hit = bool(table_lookup.get("hit"))
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:tool.call.completed:table_parse",
        event_type="tool.call.completed",
        step_id="table_parse",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "toolId": table_identity["toolId"],
          "sideEffectLevel": "read",
          "stableArgs": table_identity["stableArgs"],
          "permissionScope": table_identity["permissionScope"],
          "output": table_for_pd,
          "validity": {
            "status": "valid",
            "sourceHashes": {"table": stable_hash(task["input"].get("table"))},
          },
          "source": "workgraph.benchmark",
          "cacheReuse": table_hit,
        },
      )
    )
    records["raw/tool_calls.jsonl"].append(
      {
        "tool_call_id": f"tool:{run_id}:table_parse",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "tool_name": "tabmwp_table_parser",
        "executed": not table_hit,
        "cache_status": "hit" if table_hit else table_lookup.get("reason", "miss"),
        "latency_ms": 0,
        "input_hash": stable_hash(task["input"].get("table")),
        "output_hash": stable_hash(table_for_pd),
      }
    )
    obs_payload = {
      "columns": list(table_for_pd.keys()) if isinstance(table_for_pd, dict) else [],
      "row_count": task.get("metadata", {}).get("row_num"),
      "column_count": task.get("metadata", {}).get("column_num"),
    }
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:context.build.completed:table",
        event_type="context.build.completed",
        step_id="table_context",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "resourceId": f"tabmwp:{task['task_id']}:table",
          "output": obs_payload,
          "contentHash": stable_hash(obs_payload),
          "provenance": {
            "resourceId": f"tabmwp:{task['task_id']}:table",
            "sourceHash": stable_hash(table_for_pd),
          },
        },
      )
    )
    records["raw/observations.jsonl"].append(
      {
        "observation_id": f"obs:{run_id}:table",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "source": "tabmwp_table",
        "cache_status": "source_event_ingested",
        "payload": obs_payload,
      }
    )
  else:
    tau2_payload = run_tau2_official(
      run_dir,
      run_id,
      client.model,
      task,
      cache,
      tau2_timeout,
      tau2_subprocess_timeout,
    )
    obs_payload = {
      "domain": task["input"].get("domain"),
      "has_initial_state": task["input"].get("initial_state") is not None,
      "gold_hidden_from_agent_prompt": True,
      "official_tau2_simulation_id": tau2_payload.get("simulation", {}).get("id"),
      "official_tau2_termination_reason": tau2_payload.get("simulation", {}).get("termination_reason"),
    }
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:context.build.completed:scenario",
        event_type="context.build.completed",
        step_id="scenario_context",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "resourceId": f"tau2:{task['task_id']}:scenario",
          "output": obs_payload,
          "contentHash": stable_hash(obs_payload),
          "provenance": {
            "resourceId": f"tau2:{task['task_id']}:scenario",
            "sourceHash": stable_hash(task["input"]),
          },
        },
      )
    )
    records["raw/observations.jsonl"].append(
      {
        "observation_id": f"obs:{run_id}:scenario",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "source": "tau2_task_slice",
        "cache_status": "source_event_ingested",
        "payload": obs_payload,
      }
    )
    append_tau2_official_trace(records, run_dir, run_id, task, method, cache, tau2_payload)
    reward_info = tau2_payload["simulation"]["reward_info"]
    success = float(reward_info.get("reward") or 0) >= 1.0
    score_details = {
      "scorer": "tau2_official_reward",
      "reward": reward_info.get("reward"),
      "reward_info": reward_info,
      "termination_reason": tau2_payload["simulation"].get("termination_reason"),
      "official_task_id": tau2_payload.get("official_task_id"),
      "user_cost_usd": tau2_agent_usage(tau2_payload)["user_cost_usd"],
    }
    cache.ingest(
      cache.event(
        run_id=run_id,
        event_id=f"{run_id}:eval.completed:score",
        event_type="eval.completed",
        step_id="score",
        agent_id=f"agent.{benchmark}.deepseek_pro",
        payload={
          "target": f"{benchmark}:{task['task_id']}",
          "test": score_details["scorer"],
          "result": {"success": success, "score_details": score_details},
          "validityProof": {
            "sourceHash": stable_hash(tau2_payload["simulation"].get("messages")),
            "testHash": stable_hash(score_details["scorer"]),
            "envHash": stable_hash({"model": client.model, "benchmark": benchmark, "runner": "tau2_official"}),
          },
          "output": {"success": success, "score_details": score_details},
        },
      )
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    usage = tau2_agent_usage(tau2_payload)
    records["raw/verifications.jsonl"].append(
      {
        "verification_id": f"verify:{run_id}:score",
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "verifier": score_details["scorer"],
        "success": success,
        "cache_status": "source_event_ingested",
        "payload": score_details,
      }
    )
    records["raw/task_results.jsonl"].append(
      {
        "run_id": run_id,
        "task_id": task["task_id"],
        "benchmark": benchmark,
        "method": method.name,
        "repeat_pass": repeat_index + 1,
        "agent_id": f"agent.{benchmark}.deepseek_pro",
        "success": success,
        "latency_ms": latency_ms,
        "mode": "real",
        "final_answer_hash": stable_hash(tau2_payload["simulation"].get("messages")),
        "evaluator": score_details["scorer"],
      }
    )
    append_runtime_events(records, run_id, task, method, "agent.run.finished")
    return {
      "run_id": run_id,
      "method": method.name,
      "benchmark": benchmark,
      "task_id": task["task_id"],
      "repeat_pass": repeat_index + 1,
      "success": success,
      "latency_ms": latency_ms,
      "agent_cost_usd": usage["agent_cost_usd"],
      "agent_prompt_tokens": usage["prompt_tokens"],
      "agent_completion_tokens": usage["completion_tokens"],
      "prediction": {"official_tau2_simulation": tau2_payload["simulation"]["id"]},
      "gold_answer": None,
      "score_details": score_details,
    }

  prompt_hash = record_prompt(records, run_id, task, method, cache, messages)
  max_tokens = {
    "financebench": 4096,
    "tau2-bench": 3072,
    "promptpg-tabmwp": 1600,
  }[benchmark]
  request_payload = client.request_payload(messages, max_tokens=max_tokens, response_json=True)
  computation_lookup = model_call_lookup(cache, client, request_payload)
  response_executed = not computation_lookup.get("hit")
  if response_executed:
    response = client.chat(messages, max_tokens=max_tokens, response_json=True)
    ingest_model_call(
      cache,
      run_id=run_id,
      benchmark=benchmark,
      client=client,
      request_payload=request_payload,
      response=response,
      step_id="agent_prediction",
    )
  else:
    response = cached_response_from_computation(computation_lookup, request_payload)
    response["raw"] = {
      **(response.get("raw") or {}),
      "cacheReuse": True,
    }
    ingest_model_call(
      cache,
      run_id=run_id,
      benchmark=benchmark,
      client=client,
      request_payload=request_payload,
      response=response,
      step_id="agent_prediction",
    )
  response_path = run_dir / "payloads" / "llm_responses" / f"{slug(run_id)}_agent.json"
  write_json(
    response_path,
    {
      "request": response["request"],
      "response": response["raw"],
      "provider_attempts": response.get("attempts") or [],
    },
  )
  parsed = extract_json(response["content"])

  success, score_details = score_answer(benchmark, parsed, task.get("gold", {}))
  cache.ingest(
    cache.event(
      run_id=run_id,
      event_id=f"{run_id}:eval.completed:score",
      event_type="eval.completed",
      step_id="score",
      agent_id=f"agent.{benchmark}.deepseek_pro",
      payload={
        "target": f"{benchmark}:{task['task_id']}",
        "test": score_details.get("scorer"),
        "result": {"success": success, "score_details": score_details},
        "validityProof": {
          "sourceHash": stable_hash(parsed),
          "testHash": stable_hash(score_details.get("scorer")),
          "envHash": stable_hash({"model": client.model, "benchmark": benchmark}),
        },
        "output": {"success": success, "score_details": score_details},
      },
    )
  )

  latency_ms = round((time.perf_counter() - started) * 1000, 2)
  usage = response["usage"]
  records["raw/llm_calls.jsonl"].append(
    {
      "call_id": f"llm:{run_id}:agent",
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": benchmark,
      "method": method.name,
      "provider": PROVIDER,
      "model": client.model,
      "purpose": "agent_prediction",
      "executed": response_executed,
      "input_tokens": int(usage.get("prompt_tokens") or 0),
      "output_tokens": int(usage.get("completion_tokens") or 0),
      "cached_input_tokens": int(usage.get("prompt_cache_hit_tokens") or 0),
      "cost_usd": response["cost_usd"],
      "latency_ms": response["latency_ms"],
      "prefix_hash": prompt_hash,
      "finish_reason": response["finish_reason"],
      "response_path": str(response_path.relative_to(run_dir)),
      "workcache_status": workcache_lookup_status(computation_lookup, response_executed),
      "provider_attempts": len(response.get("attempts") or []),
    }
  )
  records["raw/verifications.jsonl"].append(
    {
      "verification_id": f"verify:{run_id}:score",
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": benchmark,
      "method": method.name,
      "verifier": score_details.get("scorer"),
      "success": success,
      "cache_status": "source_event_ingested",
      "payload": score_details,
    }
  )
  records["raw/task_results.jsonl"].append(
    {
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": benchmark,
      "method": method.name,
      "repeat_pass": repeat_index + 1,
      "agent_id": f"agent.{benchmark}.deepseek_pro",
      "success": success,
      "latency_ms": latency_ms,
      "mode": "real",
      "final_answer_hash": stable_hash(parsed),
      "evaluator": score_details.get("scorer"),
    }
  )
  append_runtime_events(records, run_id, task, method, "agent.run.finished")
  return {
    "run_id": run_id,
    "method": method.name,
    "benchmark": benchmark,
    "task_id": task["task_id"],
    "repeat_pass": repeat_index + 1,
    "success": success,
    "latency_ms": latency_ms,
    "agent_cost_usd": response["cost_usd"],
    "agent_prompt_tokens": int(usage.get("prompt_tokens") or 0),
    "agent_completion_tokens": int(usage.get("completion_tokens") or 0),
    "prediction": parsed,
    "gold_answer": task.get("gold", {}).get("answer"),
    "score_details": score_details,
  }


def record_task_failure(
  records: dict[str, list[dict[str, Any]]],
  run_id: str,
  task: dict[str, Any],
  method: MethodSpec,
  error: Exception,
  latency_ms: float,
  repeat_index: int,
) -> dict[str, Any]:
  error_details = {
    "scorer": "runner_error",
    "error_type": type(error).__name__,
    "error_message": str(error)[:2000],
  }
  append_runtime_events(records, run_id, task, method, "agent.run.failed")
  records["raw/verifications.jsonl"].append(
    {
      "verification_id": f"verify:{run_id}:runner_error",
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": task["benchmark"],
      "method": method.name,
      "verifier": "runner_error",
      "success": False,
      "cache_status": "not_applicable",
      "payload": error_details,
    }
  )
  records["raw/task_results.jsonl"].append(
    {
      "run_id": run_id,
      "task_id": task["task_id"],
      "benchmark": task["benchmark"],
      "method": method.name,
      "repeat_pass": repeat_index + 1,
      "agent_id": f"agent.{task['benchmark']}.deepseek_pro",
      "success": False,
      "latency_ms": latency_ms,
      "mode": "real",
      "final_answer_hash": "",
      "evaluator": "runner_error",
      "error_type": error_details["error_type"],
      "error_message": error_details["error_message"],
    }
  )
  return {
    "run_id": run_id,
    "method": method.name,
    "benchmark": task["benchmark"],
    "task_id": task["task_id"],
    "repeat_pass": repeat_index + 1,
    "success": False,
    "latency_ms": latency_ms,
    "agent_cost_usd": 0.0,
    "agent_prompt_tokens": 0,
    "agent_completion_tokens": 0,
    "prediction": {"error": error_details},
    "gold_answer": task.get("gold", {}).get("answer"),
    "score_details": error_details,
  }


def summarize(
  predictions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
  by_benchmark: dict[str, list[dict[str, Any]]] = {}
  by_method_benchmark: dict[tuple[str, str], list[dict[str, Any]]] = {}
  for row in predictions:
    by_benchmark.setdefault(row["benchmark"], []).append(row)
    by_method_benchmark.setdefault((row["method"], row["benchmark"]), []).append(row)

  benchmark_rows: list[dict[str, Any]] = []
  for benchmark, items in sorted(by_benchmark.items()):
    benchmark_rows.append(
      {
        "benchmark": benchmark,
        "tasks": len(items),
        "successes": sum(1 for item in items if item["success"]),
        "success_rate": round(sum(1 for item in items if item["success"]) / max(1, len(items)), 4),
        "agent_cost_usd": round(sum(float(item["agent_cost_usd"]) for item in items), 8),
        "prompt_tokens": sum(int(item["agent_prompt_tokens"]) for item in items),
        "completion_tokens": sum(int(item["agent_completion_tokens"]) for item in items),
        "latency_ms": round(sum(float(item["latency_ms"]) for item in items), 2),
      }
    )
  method_benchmark_rows: list[dict[str, Any]] = []
  for (method, benchmark), items in sorted(by_method_benchmark.items()):
    method_benchmark_rows.append(
      {
        "method": method,
        "benchmark": benchmark,
        "tasks": len(items),
        "successes": sum(1 for item in items if item["success"]),
        "success_rate": round(sum(1 for item in items if item["success"]) / max(1, len(items)), 4),
        "agent_cost_usd": round(sum(float(item["agent_cost_usd"]) for item in items), 8),
        "prompt_tokens": sum(int(item["agent_prompt_tokens"]) for item in items),
        "completion_tokens": sum(int(item["agent_completion_tokens"]) for item in items),
        "latency_ms": round(sum(float(item["latency_ms"]) for item in items), 2),
      }
    )
  summary = {
    "total_tasks": len(predictions),
    "total_successes": sum(1 for item in predictions if item["success"]),
    "overall_success_rate": round(sum(1 for item in predictions if item["success"]) / max(1, len(predictions)), 4),
    "by_benchmark": benchmark_rows,
    "by_method_benchmark": method_benchmark_rows,
  }
  return summary, benchmark_rows, method_benchmark_rows


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--limit", type=int, default=3)
  parser.add_argument("--exp-id", default="real_deepseek_v4_pro_3x3")
  parser.add_argument("--output-dir", type=Path, default=None)
  parser.add_argument("--finance-top-k", type=int, default=6)
  parser.add_argument(
    "--benchmarks",
    default="tau2-bench,financebench,promptpg-tabmwp",
    help="Comma-separated benchmark names to run.",
  )
  parser.add_argument(
    "--repeat-passes",
    type=int,
    default=1,
    help="Run the same selected tasks multiple times inside each method+benchmark cache scope.",
  )
  parser.add_argument("--tau2-timeout", type=int, default=300)
  parser.add_argument("--tau2-subprocess-timeout", type=int, default=420)
  parser.add_argument("--provider-timeout", type=int, default=180)
  parser.add_argument("--provider-retries", type=int, default=2)
  parser.add_argument("--provider-retry-backoff", type=float, default=2.0)
  parser.add_argument(
    "--continue-on-task-error",
    action="store_true",
    help="Record task-level runner errors as failed tasks instead of aborting the whole run.",
  )
  parser.add_argument(
    "--method-suite",
    choices=["main", "table1", "ablation", "table2", "mechanism", "table3", "all"],
    default="main",
    help="Method suite to run. main/table1 runs the five main-result methods.",
  )
  args = parser.parse_args()

  load_dotenv(ROOT / ".env")
  model = os.environ.get("WORKGRAPH_MODEL", DEFAULT_MODEL)
  base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
  api_key = os.environ.get("DEEPSEEK_API_KEY")
  if not api_key:
    raise RuntimeError("DEEPSEEK_API_KEY is not set; fill local .env before running real samples")
  if args.repeat_passes < 1:
    raise RuntimeError("--repeat-passes must be >= 1")
  benchmarks = [item.strip() for item in args.benchmarks.split(",") if item.strip()]
  unknown_benchmarks = [benchmark for benchmark in benchmarks if benchmark not in BENCHMARK_TASK_FILES]
  if unknown_benchmarks:
    raise RuntimeError(f"unknown benchmark(s): {', '.join(unknown_benchmarks)}")
  if not benchmarks:
    raise RuntimeError("--benchmarks must select at least one benchmark")
  if args.tau2_timeout < 1 or args.tau2_subprocess_timeout < 1:
    raise RuntimeError("--tau2-timeout and --tau2-subprocess-timeout must be >= 1")
  if args.provider_timeout < 1 or args.provider_retries < 0 or args.provider_retry_backoff < 0:
    raise RuntimeError("--provider-timeout must be >= 1, --provider-retries >= 0, and --provider-retry-backoff >= 0")
  methods = select_methods(args.method_suite)

  run_dir = args.output_dir or ROOT / "outputs" / "workcache_benchmarks" / args.exp_id
  prepare_run_dir(run_dir)
  records: dict[str, list[dict[str, Any]]] = {
    rel_path: []
    for rel_path in REQUIRED_TRACE_FILES
    if rel_path.endswith(".jsonl")
  }

  config = {
    "trace_schema_version": TRACE_SCHEMA_VERSION,
    "mode": "real",
    "method_suite": args.method_suite,
    "methods": [
      {
        "name": method.name,
        "removed_component": method.removed_component,
        "table": method.table,
        "cache_config": method.cache_config,
      }
      for method in methods
    ],
    "provider": PROVIDER,
    "model": model,
    "base_url": base_url,
    "api_key_present": True,
    "api_key_value_stored": False,
    "created_at": utc_now(),
    "limit_per_benchmark": args.limit,
    "repeat_passes": args.repeat_passes,
    "benchmarks": benchmarks,
    "cache_scope_rule": "cache state is isolated by method and benchmark within this run",
    "hypha_commit": hypha_commit(),
    "pricing": {
      "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
      "retrieved_date": "2026-07-05",
      "model": "deepseek-v4-pro",
      "cache_hit_input_usd_per_1m": DEEPSEEK_V4_PRO_CACHE_HIT_INPUT_PER_1M,
      "cache_miss_input_usd_per_1m": DEEPSEEK_V4_PRO_CACHE_MISS_INPUT_PER_1M,
      "output_usd_per_1m": DEEPSEEK_V4_PRO_OUTPUT_PER_1M,
    },
    "fairness": {
      "gold_in_agent_prompt": False,
      "gold_used_only_for_scoring": True,
      "experiment_side_optimization": False,
    },
    "tau2_runner": {
      "mode": "official_tau2_runner",
      "python": str(TAU2_PYTHON),
      "script": str(TAU2_OFFICIAL_RUNNER),
      "fallback_score_allowed": False,
      "timeout_seconds": args.tau2_timeout,
      "subprocess_timeout_seconds": args.tau2_subprocess_timeout,
      "continue_on_task_error": args.continue_on_task_error,
    },
    "provider_retries": {
      "timeout_seconds": args.provider_timeout,
      "max_retries": args.provider_retries,
      "retry_backoff_seconds": args.provider_retry_backoff,
      "transient_errors": [
        "TimeoutError",
        "URLError",
        "IncompleteRead",
        "RemoteDisconnected",
        "HTTP 408/409/425/429/5xx",
      ],
    },
  }
  write_json(run_dir / "config.json", config)

  client = DeepSeekClient(
    model=model,
    base_url=base_url,
    api_key=api_key,
    timeout_seconds=args.provider_timeout,
    max_retries=args.provider_retries,
    retry_backoff_seconds=args.provider_retry_backoff,
  )
  predictions: list[dict[str, Any]] = []
  for method in methods:
    for benchmark in config["benchmarks"]:
      cache = HyphaWorkCacheSession(method, benchmark, run_dir)
      tasks = read_jsonl(BENCHMARK_TASK_FILES[benchmark], args.limit)
      for repeat_index in range(args.repeat_passes):
        for task_index, task in enumerate(tasks, start=1):
          run_id = task_run_id(args.exp_id, method, benchmark, task, repeat_index, args.repeat_passes)
          print(
            f"[{utc_now()}] task {task_index}/{len(tasks)} pass "
            f"{repeat_index + 1}/{args.repeat_passes} | {method.name} | "
            f"{benchmark} | {task['task_id']}",
            flush=True,
          )
          task_started = time.perf_counter()
          try:
            predictions.append(
              run_task(
                client,
                records,
                run_dir,
                args.exp_id,
                method,
                cache,
                benchmark,
                task,
                args.finance_top_k,
                repeat_index=repeat_index,
                repeat_count=args.repeat_passes,
                tau2_timeout=args.tau2_timeout,
                tau2_subprocess_timeout=args.tau2_subprocess_timeout,
              )
            )
          except Exception as error:
            if not args.continue_on_task_error:
              raise
            latency_ms = round((time.perf_counter() - task_started) * 1000, 2)
            print(
              f"[{utc_now()}] task failed and recorded | {method.name} | "
              f"{benchmark} | {task['task_id']} | {type(error).__name__}: {str(error)[:300]}",
              flush=True,
            )
            predictions.append(
              record_task_failure(
                records,
                run_id,
                task,
                method,
                error,
                latency_ms,
                repeat_index,
              )
            )
      append_hypha_cache_snapshot(records, cache, cache.replay_snapshot())

  for rel_path, rows in records.items():
    write_jsonl(run_dir / rel_path, rows)
  write_jsonl(run_dir / "derived" / "predictions.jsonl", predictions)
  summary, summary_rows, method_benchmark_rows = summarize(predictions)
  write_json(run_dir / "derived" / "summary.json", summary)
  write_csv(run_dir / "derived" / "summary_by_benchmark.csv", summary_rows)
  write_csv(run_dir / "derived" / "summary_by_method_benchmark.csv", method_benchmark_rows)
  table_outputs = build_tables(run_dir)

  print(f"run_dir: {run_dir}")
  print(f"model: {model}")
  print(f"method_suite: {args.method_suite}")
  print(f"repeat_passes: {args.repeat_passes}")
  print(f"methods: {', '.join(method.name for method in methods)}")
  print(f"tasks: {summary['total_tasks']}")
  print(f"success_rate: {summary['overall_success_rate']:.4f}")
  for row in method_benchmark_rows:
    print(
      f"{row['method']} | {row['benchmark']}: {row['successes']}/{row['tasks']} "
      f"cost=${row['agent_cost_usd']:.8f} latency_ms={row['latency_ms']:.2f}"
    )
  for name, path in table_outputs.items():
    print(f"{name}: {path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
