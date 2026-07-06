# WorkCache Benchmark Server Run

This note documents how to move the WorkCache benchmark data to a server and
start a fresh run there without committing data, API keys, or generated outputs.

## Git Code

Clone the experiment repo on the server:

```bash
git clone https://github.com/CodeSoul-co/workgraph.git
cd workgraph
```

Clone or place Hypha next to `workgraph` if the server does not already have it:

```bash
cd ..
git clone https://github.com/CodeSoul-co/Hypha.git
cd Hypha
git checkout cache-base
cd ../workgraph
```

The runner expects Hypha at `../Hypha` by default for the current run command.

## Restore Data Package

Copy the local transfer archive to the server and extract it at the workgraph
repo root:

```bash
tar -xzf workcache_server_data_20260706.tar.gz -C /path/to/workgraph
```

The package contains:

- `data/raw/benchmarks/financebench/`
- `outputs/benchmarks/eval_slices/`
- `outputs/benchmarks/tool_readiness.json`

It intentionally does not contain `.env`, API keys, Python virtualenvs, or
ignored dependency checkouts. It also does not contain interrupted benchmark
checkpoints; the server run should start fresh.

## Server Dependencies

Install local tools and benchmark dependencies:

```bash
scripts/benchmarks/bootstrap.sh clone
scripts/benchmarks/bootstrap.sh env-tau2
scripts/benchmarks/setup_benchmark_tools.sh tau2
scripts/benchmarks/setup_benchmark_tools.sh financebench
scripts/benchmarks/setup_benchmark_tools.sh tabmwp
```

Make sure these command-line tools exist on the server:

```bash
uv --version
node --version
npm --version
pdftotext -v
rg --version
```

## Environment

Create `.env` on the server. Do not commit it.

```bash
cat > .env <<'EOF'
WORKGRAPH_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_API_KEY=replace_with_server_key
EOF
```

## Fresh Run Command

Start the 50-sample run. The `all` method suite is ordered as:
`No Cache -> WorkCache Full -> remaining baselines/ablations/mechanisms`.

```bash
python3 experiments/workcache_benchmarks/run_real_samples.py \
  --limit 50 \
  --benchmarks tau2-bench,financebench,promptpg-tabmwp \
  --method-suite all \
  --repeat-passes 2 \
  --continue-on-task-error \
  --tau2-timeout 300 \
  --tau2-subprocess-timeout 420 \
  --provider-timeout 180 \
  --provider-retries 2 \
  --provider-retry-backoff 2.0 \
  --exp-id real_hypha_all_50x2_server
```

Add `--resume` only if the server run is interrupted after it has started.

## Expected Outputs

When the run completes, these files are generated:

- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table1_main_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table2_ablation_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/table3_mechanism_results.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/summary_by_benchmark.csv`
- `outputs/workcache_benchmarks/real_hypha_all_50x2_server/derived/summary_by_method_benchmark.csv`
