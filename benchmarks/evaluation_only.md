# Evaluation-Only Implementation Path

The benchmark setup does not need PromptPG policy training or benchmark-specific model training. For Workgraph, use the benchmarks as fixed evaluation task sources and keep the comparison protocol stable.

## Recommended Local Path

1. Export benchmark tasks into a neutral JSONL format:

```sh
scripts/benchmarks/export_eval_slices.py --benchmark all
```

2. Build Workgraph runners that read each JSONL task, call the candidate agent or MAS workflow, and write predictions under `outputs/benchmarks/runs/`.

3. Score predictions with benchmark-specific evaluators:

- tau2-bench: use the upstream `tau2` CLI and domain/task evaluation semantics when running interactive tool-user simulations.
- WebArena: use the raw task configs for planning and BrowserGym/AgentLab or a self-hosted WebArena deployment for browser execution.
- FinanceBench: compare open-book financial QA answers against the gold answer and evidence under a fixed prompt/retrieval protocol.
- PromptPG/TabMWP: use direct answer accuracy by question type; no policy-gradient selector is needed if the goal is fair evaluation rather than reproducing PromptPG training.

## Why This Avoids Training

- PromptPG training learns a prompt-example selector. For evaluation-only comparisons, Workgraph can fix a zero-shot/few-shot prompt protocol or compare agents directly on the TabMWP test/test1k questions.
- WebArena does not require training. It requires a browser environment and website state. The newer BrowserGym/AgentLab path can wrap WebArena tasks without relying on this repo's old pinned Playwright dependency.
- FinanceBench is already a fixed open-book QA sample.
- tau2-bench is an interactive evaluation harness; its training extras are optional.

## Output Format

Each exported JSONL row has:

- `benchmark`: source benchmark id.
- `task_id`: stable benchmark-local id.
- `input`: fields allowed for the evaluated agent.
- `gold`: answer or evaluator metadata, not intended to be included in the model prompt.
- `metadata`: provenance, split, and runtime requirements.

The generated JSONL files are ignored because they may contain benchmark data. Regenerate them locally as needed.
