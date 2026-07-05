#!/usr/bin/env python3
"""Shared protocol definitions for WorkCache benchmark experiments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TRACE_SCHEMA_VERSION = "workcache-benchmark-trace-v1"

DIRECT_BENCHMARKS = ("tau2-bench", "financebench", "promptpg-tabmwp")

BENCHMARK_TASK_FILES = {
  "tau2-bench": ROOT / "outputs" / "benchmarks" / "eval_slices" / "tau2_all.jsonl",
  "financebench": ROOT / "outputs" / "benchmarks" / "eval_slices" / "financebench.jsonl",
  "promptpg-tabmwp": ROOT
  / "outputs"
  / "benchmarks"
  / "eval_slices"
  / "promptpg_tabmwp_test1k.jsonl",
}

REQUIRED_TRACE_FILES = (
  "config.json",
  "raw/runtime_events.jsonl",
  "raw/llm_calls.jsonl",
  "raw/tool_calls.jsonl",
  "raw/observations.jsonl",
  "raw/verifications.jsonl",
  "raw/task_results.jsonl",
  "cache/cache_ops.jsonl",
  "cache/workcache_source_events.jsonl",
  "cache/validity_checks.jsonl",
  "cache/tree_updates.jsonl",
  "cache/evictions.jsonl",
  "graph/work_graph_nodes.jsonl",
  "graph/work_graph_edges.jsonl",
  "graph/demand_signals.jsonl",
  "prompts/prompt_assemblies.jsonl",
)

TABLE1_COLUMNS = (
  "Method",
  "API Cost",
  "Input Tokens",
  "LLM Calls",
  "Tool Calls",
  "Job Time",
  "Stale Hit Rate",
  "Success Rate",
)

TABLE2_COLUMNS = (
  "Method",
  "Removed Component",
  "API Cost",
  "Input Tokens",
  "LLM Calls",
  "Tool Calls",
  "Job Time",
  "Stale Hit Rate",
  "Success Rate",
)

TABLE3_COLUMNS = (
  "Method",
  "Demand Precision",
  "Demand Recall",
  "Critical Path Hit Rate",
  "Eviction Mistake Rate",
  "Tree Lookup p95",
)


@dataclass(frozen=True)
class MethodSpec:
  name: str
  removed_component: str
  cache_config: dict[str, bool]
  table: str


BASE_CACHE_CONFIG = {
  "PromptPrefixTree": True,
  "PlanTree": True,
  "ComputationTree": True,
  "ToolTree": True,
  "ObservationTree": True,
  "VerificationTree": True,
  "WorkGraphDemand": True,
  "TreeUtilityPropagation": True,
  "ValidityRules": True,
  "PrefixMaterializer": True,
}


def cache_config(**overrides: bool) -> dict[str, bool]:
  config = dict(BASE_CACHE_CONFIG)
  config.update(overrides)
  return config


TABLE1_METHODS = (
  MethodSpec(
    "No Cache",
    "All cache components disabled",
    cache_config(
      PromptPrefixTree=False,
      PlanTree=False,
      ComputationTree=False,
      ToolTree=False,
      ObservationTree=False,
      VerificationTree=False,
      WorkGraphDemand=False,
      TreeUtilityPropagation=False,
      ValidityRules=False,
      PrefixMaterializer=False,
    ),
    "table1",
  ),
  MethodSpec(
    "Prompt Template Only",
    "Only static prompt template reuse enabled",
    cache_config(
      PlanTree=False,
      ComputationTree=False,
      ToolTree=False,
      ObservationTree=False,
      VerificationTree=False,
      WorkGraphDemand=False,
      TreeUtilityPropagation=False,
      ValidityRules=True,
    ),
    "table1",
  ),
  MethodSpec(
    "Plan Cache Only",
    "Only planning artifact reuse enabled",
    cache_config(
      PromptPrefixTree=False,
      ComputationTree=False,
      ToolTree=False,
      ObservationTree=False,
      VerificationTree=False,
      WorkGraphDemand=False,
      TreeUtilityPropagation=False,
      PrefixMaterializer=False,
    ),
    "table1",
  ),
  MethodSpec(
    "Tool Result Cache Only",
    "Only tool result reuse enabled",
    cache_config(
      PromptPrefixTree=False,
      PlanTree=False,
      ComputationTree=False,
      ObservationTree=False,
      VerificationTree=False,
      WorkGraphDemand=False,
      TreeUtilityPropagation=False,
      PrefixMaterializer=False,
    ),
    "table1",
  ),
  MethodSpec("WorkCache Full", "None", cache_config(), "table1"),
)

TABLE2_METHODS = (
  MethodSpec("WorkCache Full", "None", cache_config(), "table2"),
  MethodSpec(
    "w/o Work Graph Demand",
    "Work Graph future demand and steps-to-use scheduling signals",
    cache_config(WorkGraphDemand=False),
    "table2",
  ),
  MethodSpec(
    "w/o Tree Utility Propagation",
    "Leaf-to-root utility aggregation inside cache trees",
    cache_config(TreeUtilityPropagation=False),
    "table2",
  ),
  MethodSpec(
    "w/o Validity Rules",
    "File hash, tool args, environment, and dependency validity checks",
    cache_config(ValidityRules=False),
    "table2",
  ),
  MethodSpec(
    "w/o PromptPrefixTree",
    "Stable prompt prefix block tree",
    cache_config(PromptPrefixTree=False, PrefixMaterializer=False),
    "table2",
  ),
  MethodSpec("w/o PlanTree", "Plan template and planning artifact cache", cache_config(PlanTree=False), "table2"),
  MethodSpec("w/o ToolTree", "Tool result cache", cache_config(ToolTree=False), "table2"),
  MethodSpec(
    "w/o ObservationTree",
    "File, web, database, and environment observation cache",
    cache_config(ObservationTree=False),
    "table2",
  ),
  MethodSpec(
    "w/o VerificationTree",
    "Test, lint, and judge verification result cache",
    cache_config(VerificationTree=False),
    "table2",
  ),
  MethodSpec(
    "w/o Prefix Materializer",
    "Stable prefix assembly from logical prompt blocks",
    cache_config(PrefixMaterializer=False),
    "table2",
  ),
)

TABLE3_METHODS = (
  MethodSpec(
    "LRU Runtime Cache",
    "WorkGraph demand and tree utility disabled; eviction by recency",
    cache_config(WorkGraphDemand=False, TreeUtilityPropagation=False),
    "table3",
  ),
  MethodSpec(
    "TTL Runtime Cache",
    "WorkGraph demand and tree utility disabled; eviction by TTL",
    cache_config(WorkGraphDemand=False, TreeUtilityPropagation=False),
    "table3",
  ),
  MethodSpec(
    "WorkGraph-guided",
    "WorkGraph demand enabled without tree utility propagation",
    cache_config(TreeUtilityPropagation=False),
    "table3",
  ),
  MethodSpec(
    "WorkGraph + Tree Utility",
    "WorkGraph demand and tree utility propagation enabled",
    cache_config(),
    "table3",
  ),
)

ALL_METHODS = TABLE1_METHODS + tuple(
  method for method in TABLE2_METHODS + TABLE3_METHODS if method.name != "WorkCache Full"
)

AGENT_FLOWS: dict[str, dict[str, Any]] = {
  "tau2-bench": {
    "task_family": "interactive customer-support task with domain tools",
    "preferred_evaluator": "Upstream tau2 runner, user simulator, domain tools, and reward checks",
    "prompt": "upstream tau2 llm_agent/user_simulator prompts captured from verbose LLM logs",
    "tools": [
      "tau2 domain tools",
      "knowledge/BM25 retrieval when the domain supports it",
      "sandbox shell only when the upstream task requires it",
    ],
    "steps": [
      "Load domain, task, user scenario, allowed tools, and policy context.",
      "Plan the conversation goal without exposing gold evaluation criteria.",
      "Interact with the user simulator and call tau2 domain tools as needed.",
      "Record each LLM turn, tool call, cache lookup, work graph node, and verification result.",
      "Score with upstream tau2 reward_info from action, database, NL, and communication assertions.",
    ],
    "success_metric": "official tau2 reward_info.reward >= 1.0",
  },
  "financebench": {
    "task_family": "open-book financial QA over company filings",
    "preferred_evaluator": "Fixed retrieval plus answer/evidence scorer over FinanceBench gold",
    "prompt": "prompts/financebench_agent.md",
    "tools": [
      "PDF page extraction",
      "BM25/vector retrieval",
      "calculator for numeric transformations",
      "answer normalization and fuzzy match scorer",
    ],
    "steps": [
      "Load question, company, document metadata, and referenced PDF.",
      "Retrieve candidate pages and preserve page hashes as ObservationTree records.",
      "Assemble evidence-bounded prompt; answer only from retrieved filings.",
      "Record prompt blocks, retrieval/tool traces, validity checks, and final answer.",
      "Score normalized answer match plus evidence coverage when available.",
    ],
    "success_metric": "normalized answer correctness with evidence-compatible answer text",
  },
  "promptpg-tabmwp": {
    "task_family": "table math word problem evaluation only",
    "preferred_evaluator": "TabMWP exact/normalized answer scorer; no PromptPG training",
    "prompt": "prompts/tabmwp_agent.md",
    "tools": [
      "table parser",
      "calculator or Python/sympy helper",
      "multiple-choice normalizer",
      "numeric/text answer scorer",
    ],
    "steps": [
      "Load table, question, choices, unit, and metadata.",
      "Parse table into a stable normalized representation.",
      "Plan arithmetic or lookup operations before producing a concise answer.",
      "Record table observations, calculator/tool calls, prompt assembly, and final answer.",
      "Score by exact or normalized TabMWP answer according to answer type.",
    ],
    "success_metric": "exact or normalized answer accuracy",
  },
}
