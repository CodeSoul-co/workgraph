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
