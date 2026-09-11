# Code-Geeko — nightly repo scan

A scheduled machine that scans this repo for code-health findings, asks Claude
which are worth acting on, prints a report, and remembers what it already saw.
It is **report-only**: it opens no PRs and changes no code.

Entry point: `python -m codegeeko.run`, run by
`.github/workflows/code-geeko-nightly.yml` on cron `0 6 * * *` (06:00 UTC).
GitHub queues the run late; the resulting commit usually lands between about
09:30 and 11:00 UTC. Python 3.12, dependencies from
`codegeeko/requirements.txt` (`semgrep` and `repowise` are exact-pinned
because the parsers are coupled to their JSON shapes). Manual runs are allowed
via `workflow_dispatch` and are report-only too.

## Inputs

Three collectors, each returning `(findings, ok)` and degrading to
`([], False)` rather than raising:

| Collector | What it runs | Needs |
|---|---|---|
| `collectors/repowise_collector.py` | `repowise init . --index-only`, then `repowise health --format json` | nothing external |
| `collectors/semgrep_collector.py` | `semgrep scan --config auto --json` | network for the rule registry |
| `collectors/ci_log_collector.py` | `GET /repos/{owner}/{repo}/actions/runs?per_page=20`, keeps runs whose conclusion is `failure` | `GITHUB_TOKEN`, and the workflow's `actions: read` permission |

Prior state: `.code-geeko/state.json` — the findings already seen, keyed
`source:file:finding_id`, plus each collector's last status.

Secrets: `CLAUDE_CODE_OAUTH_TOKEN` (repo secret, Max-plan subscription token
from `claude setup-token`) for the triage call, and the workflow's own
`GITHUB_TOKEN`.

## Process

1. Load `.code-geeko/state.json`.
2. Run all three collectors.
3. If every collector failed, abort before triage and exit 1 without saving
   state. Saving an empty state here would wipe the file and re-fire every
   finding later.
4. Diff against state: a finding is a delta if it is new, or its `risk_score`
   went up.
5. Triage the deltas with one Claude call (`codegeeko/triage.py`, 300s
   timeout). A triage failure is not the same as "accepted nothing" — on
   failure the run exits 1 and state is not saved, so the deltas retry
   tomorrow.
6. Print the report.
7. `REPORT_ONLY` is hardcoded `"true"` in the workflow and the code is
   safe-by-default: only a literal `"false"` opts into the fix path. Leave it
   alone.
8. Save state, holding back findings from any collector that was not `ok`
   (carried forward from the previous state) and any accepted finding the run
   did not act on.

## Outputs

- The nightly report, teed into `$GITHUB_STEP_SUMMARY` on the run page.
- `.code-geeko/state.json`, committed to `main` as `code-geeko[bot]` with the
  message `chore: update code-geeko state`. The step checks out `main`, stages
  only that one file, and rebases before pushing because the consolidation
  workflow can push to `main` at any time.

Nothing else in this repo is written by Code-Geeko. It does not touch
`Health_Tracker_Master.csv`, `habits.csv`, `schema\`, or `logs\`.

## Done when

- The workflow run is green.
- The step summary shows the report, and any collector that failed is named at
  the top of it.
- Either a fresh `chore: update code-geeko state` commit exists, or the step
  logged "State unchanged — nothing to commit."

## Failure signal

The GitHub Actions run page for "Code-Geeko Nightly" is the only signal;
nothing is written to this repo when a run fails. Read it in this order:

- Red run, failed at "Smoke-check runtime": the Claude credential or the
  bundled CLI is broken. Usually an expired `CLAUDE_CODE_OAUTH_TOKEN`.
- Red run, failed at "Pipeline self-test": `pytest tests/codegeeko` is
  failing; this is our bug, not an upstream one.
- Red run, failed at "Run Code-Geeko" with "all collectors failed": no signal
  that night, state deliberately not saved.
- Red run with "triage failed -- state NOT saved": deltas will retry
  tomorrow; no action needed unless it repeats.
- Green run with "Collectors that failed this run:" in the summary: partial
  signal. That source's findings were carried forward, not dropped.
- No commit and no run at all for a few days: the schedule stopped, which is
  the quiet failure. Check the Actions tab, not this folder.

## Tests

`tests/codegeeko/` — one test file per module, run in the workflow as
`python -m pytest tests/codegeeko -q` (the `-m` form matters: bare `pytest`
does not put the repo root on `sys.path`).
