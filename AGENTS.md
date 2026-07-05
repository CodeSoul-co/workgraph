# Repository Guidelines

## Scope

This repository is the experiment workspace for Workgraph. Keep experiment code, data notes, notebooks, scripts, outputs, and analysis materials here. Keep Hypha framework and reusable runtime changes in `CodeSoul-co/Hypha`.

## Core Library Boundary

Use `hypha` or `../Hypha` as the local Hypha core checkout. The expected core branch for cache-specific work is `cache-base`. The `hypha/` path is ignored and must not be committed here.

If a task requires changing Hypha itself, switch to the Hypha checkout and follow its local `AGENTS.md`:

- Default core development branch is `dev`.
- `cache-base` is for cache-specific changes.
- Do not sync changes made on `cache-base` back to `dev` or `main` unless explicitly requested.
- If a non-cache core bug is found while on `cache-base`, cherry-pick it to `dev`, test it there, then sync through the normal `dev` path.
- Run Hypha typecheck/build/tests before merging core changes.

## Experiment Workspace Rules

- Use this repository to do, and only do, fair experimental performance comparisons. Report performance as comparison evidence, not as experiment-side optimization claims.
- If fair comparison requires performance tuning or bug fixes in Hypha, make those changes in the Hypha checkout on `cache-base`, validate them there, and push only to `origin/cache-base`. If the change affects non-cache Hypha core functionality, follow the Hypha core workflow instead.
- Put runnable experiment code in `experiments/`.
- Put reproducible scripts in `scripts/`.
- Put notebooks in `notebooks/`.
- Put notes and summaries in `docs/`.
- Keep raw/private data under ignored paths such as `data/raw/` or `data/private/`.
- Keep generated outputs under ignored paths such as `outputs/`, `runs/`, or `artifacts/`.

## Git Workflow

This repository can be committed and pushed independently from Hypha. Do not include ignored Hypha checkouts, local secrets, dependency folders, raw/private data, or generated artifacts in commits.
