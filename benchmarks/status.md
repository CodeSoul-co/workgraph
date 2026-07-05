# Benchmark Status

Prepared on 2026-07-05 in `/Users/erwin/Downloads/codespace/workgraph`.

## Local Assets

- tau2-bench cloned at `1901a301961cbbe3fd11f3e84a2a376530c759e3`.
- WebArena cloned at `dce04686a56253aefba7b18a4fa0937cf1dc987b`.
- PromptPG cloned at `5a1a52214521590b075f545b76a4f5ce666345e3`.
- FinanceBench JSONL downloaded from Hugging Face dataset sha `e04404e3a97f69f79c14d42f24981a1c9c3bcd18`.

## Environment Status

- tau2-bench: installed with `uv sync --extra dev`; `uv run tau2 --help` and `uv run tau2 check-data` work.
- WebArena: source/data ready; pinned local install failed on Apple Silicon because `playwright==1.32.1` requires `greenlet==2.0.1`, which fails to build with the current macOS compiler stack. Use Linux/container for strict reproduction.
- FinanceBench: JSONL ready; all 84 referenced PDFs downloaded locally.
- PromptPG: source/data ready; Python 3.8 venv created, but pinned environment is not fully installable on this Apple Silicon host because old `transformers` resolves to `tokenizers==0.12.1` without a local wheel and requires Rust compilation. Upstream also expects CUDA-era PyTorch for training.

## Data Counts

- WebArena raw tasks: 812.
- FinanceBench rows: 150; unique referenced PDFs: 84.
- PromptPG TabMWP splits: train 23,059; dev 7,686; test 7,686; test1k 1,000; table images 38,431.
- tau2 domains with task data: `airline`, `banking_knowledge`, `mock`, `retail`, `telecom`.
