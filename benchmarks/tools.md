# Benchmark Tool Matrix

This document tracks the tools needed for evaluation-only Workgraph comparisons and the stricter official benchmark paths.

## Prepared Local Tools

- System tools: `uv`, `docker`, `node`, `npm`, `gh`, `pdftotext`, `rg`, `srt`.
- tau2-bench: `uv sync --extra dev --extra knowledge --extra gym`; BM25, Gym, and sandbox shell dependencies verified.
- FinanceBench: isolated Python 3.12 environment at `external/tools/financebench-tools/.venv` with PDF parsing, table/data handling, BM25, vectorization, and fuzzy matching packages.
- PromptPG/TabMWP: isolated Python 3.12 environment at `external/tools/tabmwp-tools/.venv` with table/math/fuzzy scoring packages.
- WebArena alternate chain: isolated Python 3.12 environment at `external/tools/browsergym-agentlab/.venv` with BrowserGym, `browsergym-webarena`, AgentLab, Playwright Chromium, and local NLTK tokenizer data.

Run:

```sh
scripts/benchmarks/setup_benchmark_tools.sh all
scripts/benchmarks/check_benchmark_tools.py
```

The readiness report is written to `outputs/benchmarks/tool_readiness.json`.

## Benchmark Requirements

| Benchmark | Required tools | Prepared status |
|---|---|---|
| tau2-bench | domain tools, LiteLLM/provider API, optional knowledge retrieval, optional sandbox shell | Local tools ready. API keys are still runtime secrets. |
| WebArena | browser automation, Playwright/BrowserGym or official WebArena env, self-hosted websites, login cookies, reset path | BrowserGym/AgentLab alternate chain ready. Official website deployment is pending because it requires large Docker/AMI assets. |
| FinanceBench | PDF parser, retrieval/indexing or fixed evidence protocol, answer/evidence scorer | Local PDF/retrieval tooling ready. Provider API keys are runtime secrets if an LLM is used. |
| PromptPG/TabMWP | table reader, calculator/code/math helper, exact/normalized answer scorer | Local evaluation tooling ready. Training stack intentionally not needed. |

## WebArena Official Site Assets

The official WebArena path still needs the website state, not just Python packages. This is the remaining heavy item. The helper script prepares an ignored asset directory and can download official assets when run on a host with enough disk:

```sh
scripts/benchmarks/prepare_webarena_docker_assets.sh
DOWNLOAD=1 scripts/benchmarks/prepare_webarena_docker_assets.sh
```

Current local free disk is about 93GiB, which is not enough for a cautious full download/deployment. Use a larger Linux/Docker host or cloud VM for the official full WebArena run. The BrowserGym/AgentLab package path is ready for when the WebArena site URLs are available.

References:

- BrowserGym WebArena setup: `https://github.com/ServiceNow/BrowserGym/blob/main/browsergym/webarena/README.md`
- AgentLab setup: `https://github.com/ServiceNow/AgentLab`
- Official WebArena Docker setup: `https://github.com/web-arena-x/webarena/blob/main/environment_docker/README.md`

## Runtime Secrets

No API keys are committed. Set keys in the runtime shell or a local ignored `.env` when running model-backed evaluations:

```sh
export OPENAI_API_KEY=...
export OPENROUTER_API_KEY=...
```

tau2 dense retrieval and reranker variants require the provider keys documented by tau2. WebArena/AgentLab model agents require provider keys. FinanceBench and TabMWP can also run with local rule-based scorers after predictions are generated.
