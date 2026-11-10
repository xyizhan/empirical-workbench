---
name: verify-run
description: Verify a change to the ew CLI or a study config end to end — unit tests, a fresh panel run, and an Olist batch run when the data is available. Use after editing ew/*.py or studies/*.
---

Run from the repo root. Prefer `.venv/bin/python` and `.venv/bin/ew` when they exist.

1. `ruff check .` and `python -m unittest discover -s tests`. Stop and report if either fails.
2. Panel smoke run into a NEW directory:
   `ew run studies/panel/study.json --raw studies/panel --out runs/verify-panel-$(date +%s) --batch`
   Then check `run.json`: `status` must be `passed`. Confirm that `增长统计.csv` and `index.html` exist.
3. If `../data/raw` (or `$OLIST_RAW`) contains `olist_orders_dataset.csv`, run Olist:
   `ew run studies/olist/study.json --raw ../data/raw --out runs/verify-olist-$(date +%s) --batch`
   Check that `run.json` has `status: passed` and that `verify.log` shows no failure. If `studies/olist` changed, also run with `--decision '延误定义=clock'` into a separate new directory.
4. Add `--report` only if the change touches reporting and Quarto (`QUARTO_BIN` or `quarto` on PATH) is available. Otherwise say it was skipped.
5. Never run `ew demo` or `./demo-olist`: they need an interactive TTY. Tell the user to try the classroom flow themselves if the change affects it.

Report each step as passed, failed or skipped, with the run directories, and the `reason` field from any stopped run.
