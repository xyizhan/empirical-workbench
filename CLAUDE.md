# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Tests (same as CI): `python -m unittest discover -s tests`. Use `.venv/bin/python` / `.venv/bin/ew` if the venv exists.
- Lint: `ruff check .` (bug-catching rules only, config in `pyproject.toml`). Don't run `ruff format` or black: the code uses its own compact style.
- Smoke run: `ew run studies/panel/study.json --raw studies/panel --out runs/panel-$(date +%s) --batch`
- Olist run: `ew run studies/olist/study.json --raw ../data/raw --out runs/olist-$(date +%s) --batch`. The Olist CSVs are not in the repo: they live at `../data/raw` (or `OLIST_RAW`). `raw/` and `runs/` are gitignored.
- `--out` must be a new directory. The CLI refuses to reuse an existing one.
- `ew validate STUDY` checks a config without data; `ew report RUN --source-only` writes `report.qmd` without Quarto.
- Before/after any engine change, compare exports of a fresh Olist run (both `延误定义` values) against a run from the previous commit cell by cell (numbers within 1e-9, gz decompressed) and confirm `verify.log` passes: refactors must not change results.
- Always pass `--batch` when running non-interactively. `ew demo` and `./demo-olist` need a real TTY and will error under Claude. A decision left without a value pauses the run and exits non-zero.
- `--report` / `ew report` need Quarto on PATH or `QUARTO_BIN`. Skip it unless the change is about the report.

## Architecture notes

- The contract between engine, viewers, report builders, tools and agents is `docs/run-format.md` (`study.json`, `run.json` schema `ew.run/1`, `events.jsonl`). Change it only additively; update the doc and `tests/test_cli.py` with it.
- `ew/study.py` validates and normalizes `study.json` (stages always have `candidates`, list-form `checks` with `severity`; tools are `{argv, label}`). Normalization must stay idempotent. New study keys must be added to `STUDY_KEYS`/`STAGE_KEYS` or validation rejects them.
- `ew/engine.py` only executes and records: it fills `run['stages']` and emits events through `ew/record.py`'s `Recorder`. Display, prompts and classroom pages are listeners/callbacks wired in `ew/cli.py`; event kinds must be registered in `record.EVENTS`.
- No study-specific code in `ew/`. Study-specific reports live in the study (`studies/olist/report.py`, loaded via `"report": {"builder": ...}`), as do verification tools.
- Engine is DuckDB (`ew/engine.py`), file I/O by extension in `ew/io.py`. Each candidate runs in its own `BEGIN/ROLLBACK` transaction; the working database is kept as `OUT/run.duckdb` (`ew query`). Study SQL is DuckDB dialect: strict GROUP BY, real column types, no `julianday`; add ORDER BY to exports whose row order matters.
- Runtime dependencies: `rich`, `duckdb`. pandas/openpyxl are optional (`[formats]`, for .xlsx/.dta) and must stay lazily imported.

## Conventions

- User-facing text is Chinese: terminal output, study pages, CSV export names, README. Identifiers, code comments and commit messages are English.
- Commit messages: a single imperative English sentence describing the outcome (see `git log`).
- `skills/empirical-workbench/SKILL.md` is the Agent Skill shipped to host agents. Update it when CLI behavior changes.
