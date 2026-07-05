# WorkCache Benchmark Experiments

This experiment module targets the three benchmarks that can be used locally now:

- `tau2-bench`
- `financebench`
- `promptpg-tabmwp`

WebArena is intentionally excluded from the direct-run table path until the official website environment is available. BrowserGym/AgentLab tooling is prepared, but the site state is still pending.

## Boundary

This code is for fair experiment orchestration and trace analysis only. It does not tune benchmark-side logic to improve performance. If a fair comparison requires Hypha runtime or cache fixes, make those changes in the Hypha checkout under the branch rules.

## Agent Flows

The benchmark-specific flow plan is defined in `config/agent_flows.json` and mirrored in `protocol.py`.

- tau2-bench: use the upstream interactive task flow and domain tools; record policy checks, tool calls, user-simulator turns, and official reward outputs.
- FinanceBench: use fixed retrieval over local PDFs; record retrieved page hashes, prompt assemblies, calculations, evidence, and answer scoring.
- PromptPG/TabMWP: use evaluation-only table math; record table parsing, calculator/tool calls, normalized answer, and exact/normalized scoring.

Prompts live in `prompts/` and explicitly keep gold answers and evaluator metadata out of the agent context.

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

The local workspace can use the ignored `.env` symlink:

```sh
ln -sfn ../Hypha/.env .env
```

`run_experiment.py` loads `.env` by default and records only provider key names in `config.json`, never key values.

Use simulation only to validate schema and table generation:

```sh
python3 experiments/workcache_benchmarks/run_experiment.py --exp-id smoke --limit 1
```

The output goes under ignored `outputs/workcache_benchmarks/smoke/`.

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
