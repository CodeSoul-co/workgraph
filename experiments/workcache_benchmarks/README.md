# WorkCache Benchmark Experiments

This experiment module targets the three benchmarks that can be used locally now:

- `tau2-bench`
- `financebench`
- `promptpg-tabmwp`

WebArena is intentionally excluded from the direct-run table path until the official website environment is available. BrowserGym/AgentLab tooling is prepared, but the site state is still pending.

## Boundary

This code is for fair experiment orchestration and trace analysis only. It does not tune benchmark-side logic to improve performance. If a fair comparison requires Hypha runtime or cache fixes, make those changes in the Hypha checkout under the branch rules.

Cache behavior in real runs is delegated to the Hypha `cache-base` WorkCache package through `hypha_workcache_bridge.js`. The experiment runner may translate benchmark events into Hypha `FrameworkEvent` records, but cache keys, lookups, materialization, writes, work graph nodes, and demand signals must come from Hypha WorkCache.

## Agent Flows

The benchmark-specific flow plan is defined in `config/agent_flows.json` and mirrored in `protocol.py`.

- tau2-bench: use the upstream interactive task flow, user simulator, domain tools, and official reward outputs through `tau2_official_runner.py`; no fallback judge is allowed.
- FinanceBench: use fixed retrieval over local PDFs; record retrieved page hashes, prompt assemblies, calculations, evidence, and answer scoring.
- PromptPG/TabMWP: use evaluation-only table math; record table parsing, calculator/tool calls, normalized answer, and exact/normalized scoring.

Prompts live in `prompts/` for FinanceBench, TabMWP, and simulation-only documentation. Real tau2-bench runs use the upstream tau2 agent/user prompts captured in tau2 verbose LLM logs; gold answers and evaluator metadata stay out of the agent context.

## Required Trace Outputs

Every run writes:

- `config.json`
- `raw/runtime_events.jsonl`
- `raw/llm_calls.jsonl`
- `raw/tool_calls.jsonl`
- `raw/observations.jsonl`
- `raw/verifications.jsonl`
- `raw/task_results.jsonl`
- `cache/cache_ops.jsonl`
- `cache/validity_checks.jsonl`
- `cache/tree_updates.jsonl`
- `cache/evictions.jsonl`
- `graph/work_graph_nodes.jsonl`
- `graph/work_graph_edges.jsonl`
- `graph/demand_signals.jsonl`
- `prompts/prompt_assemblies.jsonl`

The derived fixed tables are:

- `derived/table1_main_results.csv`
- `derived/table2_ablation_results.csv`
- `derived/table3_mechanism_results.csv`

## Smoke Run

Use simulation only to validate schema and table generation:

```sh
python3 experiments/workcache_benchmarks/run_experiment.py --exp-id smoke --limit 1
```

The output goes under ignored `outputs/workcache_benchmarks/smoke/`.

Use the real provider-backed runner to validate official tau2 and Hypha WorkCache integration:

```sh
python3 experiments/workcache_benchmarks/run_real_samples.py --limit 1 --method-suite main --exp-id real_hypha_workcache_official_tau2_smoke
```

The real runner requires local `.env` API keys and the upstream tau2 virtual environment at `external/benchmarks/tau2-bench/.venv`. If tau2 official execution fails, the run stops instead of writing a substitute score.

## Metrics

Table 1 and Table 2 compute:

- API Cost: sum of executed LLM call cost.
- Input Tokens: sum of executed LLM input tokens.
- LLM Calls: count of executed provider calls.
- Tool Calls: count of executed tool calls.
- Job Time: sum of task latency in milliseconds.
- Stale Hit Rate: stale cache hits divided by all cache hits.
- Success Rate: successful tasks divided by completed tasks.

Table 3 computes:

- Demand Precision: used demand signals divided by predicted demand signals.
- Demand Recall: predicted-needed demand targets divided by actual-needed demand targets.
- Critical Path Hit Rate: cache hits on critical path nodes divided by critical path nodes.
- Eviction Mistake Rate: evictions followed by recomputation divided by evictions.
- Tree Lookup p95: p95 cache lookup latency in milliseconds.
