# Benchmark Preparation

This folder documents the local benchmark assets used for fair experimental comparisons. Third-party source trees, raw benchmark data, virtual environments, generated configs, and run outputs are intentionally ignored by git.

## Local Asset Layout

- `external/benchmarks/tau2-bench`: tau2/tau3 benchmark source checkout.
- `external/benchmarks/webarena`: WebArena benchmark source checkout.
- `external/benchmarks/PromptPG`: PromptPG and TabMWP source/data checkout.
- `data/raw/benchmarks/financebench`: FinanceBench JSONL sample and referenced PDFs.
- `outputs/benchmarks`: local evaluation outputs.

## Bootstrap

Run the full local bootstrap:

```sh
scripts/benchmarks/bootstrap.sh all
```

Run individual steps:

```sh
scripts/benchmarks/bootstrap.sh clone
scripts/benchmarks/bootstrap.sh financebench
scripts/benchmarks/bootstrap.sh env-tau2
scripts/benchmarks/bootstrap.sh env-webarena
scripts/benchmarks/bootstrap.sh env-promptpg
scripts/benchmarks/check_benchmarks.py
```

## Tool Setup

Prepare benchmark tools and alternatives:

```sh
scripts/benchmarks/setup_benchmark_tools.sh all
scripts/benchmarks/check_benchmark_tools.py
```

See [tools.md](tools.md) for the tool matrix, pending runtime secrets, and WebArena official site deployment notes.

## Evaluation-Only Export

Training is not required for the local Workgraph comparison path. Export neutral task slices from the fixed benchmark data:

```sh
scripts/benchmarks/export_eval_slices.py --benchmark all
```

The generated JSONL files go to `outputs/benchmarks/eval_slices/` and stay ignored. See [evaluation_only.md](evaluation_only.md) for the implementation boundary.

## Benchmark Notes

### tau2-bench

- Source: `https://github.com/sierra-research/tau2-bench`
- Current upstream requires Python `>=3.12,<3.14` and `uv`.
- Local install command: `uv sync --extra dev` from the checkout.
- API-backed evaluations require provider keys in the checkout `.env`.

### WebArena

- Source: `https://github.com/web-arena-x/webarena`
- Upstream recommends Python 3.10, Playwright, and a self-hosted WebArena website environment.
- The 812 raw task configs live in `config_files/test.raw.json`.
- Reproducible evaluation requires self-hosting the websites, generating config files, obtaining auto-login cookies, and setting `OPENAI_API_KEY` for the baseline runner.
- On this Apple Silicon machine, the pinned `playwright==1.32.1` dependency pulls `greenlet==2.0.1`, which fails to build against the current macOS compiler stack. Use a Linux/container environment for strict reproduction unless the benchmark dependency pins are deliberately updated.

### FinanceBench

- Source: `https://huggingface.co/datasets/PatronusAI/financebench`
- License: `cc-by-nc-4.0`.
- The open-source sample has 150 QA rows.
- The JSONL references 84 unique PDF documents; the downloader fetches only those referenced PDFs from `patronus-ai/financebench`.

### PromptPG

- Source: `https://github.com/lupantech/PromptPG`
- TabMWP data is included in the repository under `data/tabmwp`.
- The cloned dataset has 38,431 table images and train/dev/test JSON splits.
- Upstream requirements target Python 3.8.10 and a CUDA-era PyTorch stack. On Apple Silicon, the pinned `transformers==4.21.1` path requires `tokenizers==0.12.1`, which needs a Rust build when no wheel is available. Use Linux/CUDA or a purpose-built container for strict reproduction.

## Fair Comparison Boundary

Keep benchmark orchestration, dataset handling, evaluation wrappers, and experiment MAS implementations in this repository. If benchmark support reveals a reusable Hypha core need such as message bus behavior, runtime communication contracts, or core adapters, make that change in the Hypha core checkout under the branch rules documented in the root `AGENTS.md`.
