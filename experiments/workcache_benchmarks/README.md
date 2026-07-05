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

The tau2 runner keeps the official half-duplex communication protocol enabled. Some OpenAI-compatible providers return assistant messages containing both text and `tool_calls`; tau2 treats those as protocol errors, so the runner normalizes them to tool-call-only messages and stores the removed text in `protocol_normalization` metadata.

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
- `cache/workcache_source_events.jsonl`
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
Use `--repeat-passes N` to rerun the same selected tasks inside the same method+benchmark cache scope. This is the intended warm-cache design check: traces keep pass-specific `run_id` values, while cache reuse remains isolated to the benchmark and method being evaluated.
Use `--benchmarks financebench,promptpg-tabmwp` for staged runs, and `--continue-on-task-error` only when a large run should record official runner timeouts or task-level infrastructure errors as failed tasks instead of discarding the whole run.
Provider-backed direct LLM calls use bounded retries for transient transport failures. Tune them with `--provider-timeout`, `--provider-retries`, and `--provider-retry-backoff`; failed attempts are recorded in response payload files and successful costs still come from the final provider usage.

## Resume

The real runner is checkpointed at task-run granularity. By default, running the same `--exp-id` starts a fresh run and clears known experiment outputs under that run directory, including persisted Hypha sqlite cache files. Add `--resume` to continue an interrupted run with the same arguments.

Resume uses:

- `checkpoint/completed_tasks.jsonl` to skip completed `run_id` values.
- `checkpoint/completed_scopes.jsonl` to avoid duplicating completed method+benchmark snapshots.
- `cache/workcache_source_events.jsonl` to replay completed source events into the Hypha sqlite cache before pending tasks continue.
- `checkpoint/run_state.json` for current `running`, `paused`, or `completed` status.

The resume path validates the requested config against the existing `config.json`. If arguments such as `--method-suite`, `--limit`, `--repeat-passes`, `--benchmarks`, `--finance-top-k`, model, or base URL differ, start a new `--exp-id` instead of resuming.

For a small staged smoke:

```sh
python3 experiments/workcache_benchmarks/run_real_samples.py --limit 1 --benchmarks promptpg-tabmwp --method-suite main --exp-id resume_smoke --stop-after-task-runs 1
python3 experiments/workcache_benchmarks/run_real_samples.py --limit 1 --benchmarks promptpg-tabmwp --method-suite main --exp-id resume_smoke --resume
```

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
- Tree Lookup p95: p95 latency of Hypha `workcache.lookup` audit events in milliseconds.
