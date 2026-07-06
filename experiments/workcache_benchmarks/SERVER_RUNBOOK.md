# WorkCache Benchmark Server Run

This note documents how to move the WorkCache benchmark data to a server and
start a fresh run there without committing data, API keys, or generated outputs.

## Git Code

Clone the experiment repo on the server:

```bash
git clone https://github.com/CodeSoul-co/workgraph.git
cd workgraph
```

Hypha is prepared by the setup script below. It creates or updates the ignored
`workgraph/hypha` checkout on `cache-base`, which is the path the runner uses by
default.

## Restore Data And Prepare Tools

Copy the local transfer archive to the server and place it at the workgraph repo
root, or pass its path to the setup script.

```bash
DEEPSEEK_API_KEY=replace_with_server_key \
  bash scripts/benchmarks/server_prepare_workcache.sh ./workcache_server_data_20260706.tar.gz
```

If `.env` already exists, the setup script leaves it unchanged. If it does not
exist and `DEEPSEEK_API_KEY` is provided, the script creates `.env` with
`WORKGRAPH_MODEL=deepseek-v4-pro` and `DEEPSEEK_BASE_URL=https://api.deepseek.com/v1`.

The package contains:

- `data/raw/benchmarks/financebench/`
- `outputs/benchmarks/eval_slices/`
- `outputs/benchmarks/tool_readiness.json`

It intentionally does not contain `.env`, API keys, Python virtualenvs, or
ignored dependency checkouts. It also does not contain interrupted benchmark
checkpoints; the server run should start fresh.

The setup script also installs or prepares:

- `workgraph/hypha` from `CodeSoul-co/Hypha` on `cache-base`
- Hypha `@hypha/workcache` dependencies and `packages/workcache/dist`
- external benchmark repos under `external/benchmarks/`
- tau2-bench Python environment and sandbox runtime
- FinanceBench local tools
- PromptPG/TabMWP local tools
- benchmark data readiness checks

Hypha npm dependencies are installed from `https://registry.npmmirror.com` by
default. Override the mirror when needed:

```bash
NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/ \
  bash scripts/benchmarks/server_prepare_workcache.sh ./workcache_server_data_20260706.tar.gz
```

Make sure these command-line tools exist on the server:

```bash
uv --version
node --version
npm --version
pdftotext -v
rg --version
```

Hypha requires Node.js >=18. On AutoDL/conda hosts, install a compatible Node if
needed:

```bash
conda install -y -c conda-forge nodejs=20
```

## Fresh Run Command

Start the 50-sample run. By default this runs all three table experiment suites.
The `all` method suite is ordered as:
`No Cache -> WorkCache Full -> remaining baselines/ablations/mechanisms`.

```bash
bash scripts/benchmarks/server_start_workcache_50x2.sh --background
```

Run one table experiment suite, or all table suites explicitly:

```bash
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table1
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table2
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table3
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table all
```

Run one benchmark, a subset, or all benchmarks:

```bash
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmark tau2-bench
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmarks tau2-bench,financebench
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmarks all
```

Choose a different sample count per benchmark, or all available tasks per
benchmark:

```bash
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --sample-limit all
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --sample-limit 1000
```

If the requested count is larger than one benchmark's available slice, that
benchmark uses all available tasks.

Add `--resume` only if the server run is interrupted after it has started:

```bash
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --resume
```

The background launcher writes:

- `outputs/workcache_benchmarks/jobs/real_hypha_all_50x2_server.pid`
- `outputs/workcache_benchmarks/jobs/real_hypha_all_50x2_server.log`

## Expected Outputs

When the run completes, these files are generated:

- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table1_main_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table2_ablation_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table3_mechanism_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/summary_by_benchmark.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/summary_by_method_benchmark.csv`
