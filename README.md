# Workgraph

This repository is the private experiment workspace around Hypha. Keep experiment code, notebooks, data notes, run outputs, and paper or analysis materials here. Keep reusable framework work in the Hypha core repository.

## Repository Boundary

- Core library: `CodeSoul-co/Hypha`, expected locally as `hypha` or `../Hypha`.
- Core branch for cache work: `cache-base`.
- Experiment workspace: this repository.
- Do not commit the Hypha checkout, build outputs, local secrets, raw/private data, or generated run artifacts to this repository.

The local `hypha` entry is ignored on purpose. It can be a symlink to `../Hypha` or a separate checkout:

```sh
ln -s ../Hypha hypha
# or
git clone --branch cache-base https://github.com/CodeSoul-co/Hypha.git hypha
```

## Core Change Rules

Use this repository for experiments by default. If an experiment requires a Hypha core change, make that change in the Hypha checkout and follow its `AGENTS.md` rules:

- Workgraph should do fair experimental performance comparisons only. Do not describe performance as the result of experiment-side optimization.
- If fair comparison requires Hypha performance tuning or bug fixes, make those changes on Hypha `cache-base`, validate them, and push only to `origin/cache-base` unless the change affects non-cache Hypha core functionality.
- Build concrete experiment workflows, experiment MAS implementations, configs, and evaluation scripts in Workgraph. Build reusable MAS support and Hypha framework capabilities, such as a message bus, runtime communication abstractions, event contracts, or core adapters, in the Hypha core repository.
- Work on `dev` by default.
- Use `cache-base` only for cache-specific work.
- Do not sync `cache-base` changes back to `dev` or `main` unless explicitly requested.
- For non-cache core bug fixes found on `cache-base`, cherry-pick the fix to `dev`, validate there, then sync through the normal path.
- Run the relevant Hypha checks before merging, including `npm run typecheck`, `npm run build`, and `npm run test:unit` for structural refactors.

## Layout

- `experiments/`: runnable experiment code and configs.
- `data/`: tracked data notes and small curated inputs; raw/private data stays ignored.
- `notebooks/`: exploratory notebooks.
- `scripts/`: local automation for experiments.
- `docs/`: experiment notes, protocol docs, and summaries.

## Server WorkCache Benchmark Run

Use the server batch scripts to reproduce the current WorkCache benchmark
environment without committing data, secrets, dependency folders, or generated
outputs. Copy `workcache_server_data_20260706.tar.gz` to the cloned repo root
before running the setup command.

Prepare the server environment:

```sh
DEEPSEEK_API_KEY=replace_with_server_key \
  bash scripts/benchmarks/server_prepare_workcache.sh ./workcache_server_data_20260706.tar.gz
```

The setup script installs Hypha npm dependencies from `https://registry.npmmirror.com`
by default. Override it if another mirror is faster on the server:

```sh
NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/ \
  bash scripts/benchmarks/server_prepare_workcache.sh ./workcache_server_data_20260706.tar.gz
```

If npm is slow or unavailable, upload `hypha_workcache_dist_fa98498.tar.gz` to
the repo root before running setup. The setup script will use that prebuilt
Hypha WorkCache dist package and skip npm install/build for WorkCache.

Hypha requires Node.js >=18. On AutoDL/conda hosts, install a compatible Node if
the setup script reports an older version:

```sh
conda install -y -c conda-forge nodejs=20
```

Start the default run. By default this runs all three table experiment suites
and all three currently prepared benchmarks: `tau2-bench`, `financebench`, and
`promptpg-tabmwp`.

```sh
bash scripts/benchmarks/server_start_workcache_50x2.sh --background
```

Run one table experiment suite, or all table suites explicitly:

```sh
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table1
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table2
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table table3
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --table all
```

Run a single benchmark, a subset, or all benchmarks explicitly:

```sh
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmark tau2-bench
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmarks tau2-bench,financebench
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --benchmarks all
```

Control sample count per benchmark with `--sample-limit N|all`. If `N` exceeds
one benchmark's available slice length, that benchmark uses all available tasks.

```sh
bash scripts/benchmarks/server_start_workcache_50x2.sh --background --sample-limit all
```

Use `--resume` only after an interrupted server run, and set `WORKCACHE_EXP_ID`
when you want separate output directories for separate runs.
