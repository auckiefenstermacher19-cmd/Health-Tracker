# repowise_sample_output.json — provenance

This fixture is **real, captured output** from running Repowise (v0.25.0) against the
`Health-Tracker-live` worktree checkout at `feature/code-geeko-pilot`. It is not
hand-written or guessed.

## What actually happened (deviating from the brief's Step 2)

The brief's documented Step 2 (`repowise export --format json`) does **not** work
after `repowise init . --index-only`, because `--index-only` skips LLM page
generation, and `export` only exports generated wiki pages. Running it produced:

```
$ repowise export --format json -o /tmp/repowise-export
No pages found. Run 'repowise init' first.
```

(exit code 0, but no usable data — the documented fallback trigger.)

## Command that actually produced this fixture

Per the brief's documented fallback, the following command was used instead. It is
noteworthy that, unlike `export`, `repowise health` supports a `--format json` flag
directly (it runs in-process, no LLM/network calls needed), so the fixture is real
structured JSON rather than plain text:

```bash
python3 -m venv /tmp/repowise-spike
source /tmp/repowise-spike/bin/activate
pip install --quiet repowise            # repowise 0.25.0

cd "Health-Tracker-live/.worktrees/feature-code-geeko-pilot"
repowise init . --index-only            # required first: builds the graph/git/dead-code index
repowise health --format json > tests/codegeeko/fixtures/repowise_sample_output.json
```

All commands were run inside WSL2 Ubuntu (`wsl -e bash -c "..."`) because the base
`repowise` package pulls in `litellm`, which needs a Rust toolchain not available in
Windows Python on this machine.

## Shape of the output

Top-level keys:
- `kpis` — aggregate scores (`hotspot_health`, `average_health`, `worst_performer_path`,
  `worst_performer_score`, `file_count`, `maintainability_average`,
  `maintainability_hotspot`, `performance_average`, `performance_hotspot`)
- `metrics` — one entry per analyzed file (`file_path`, `score`, `max_ccn`,
  `max_nesting`, `nloc`, `has_test_file`, `line_coverage_pct`, `branch_coverage_pct`,
  `duplication_pct`)
- `findings` — individual code-health "biomarkers" (`biomarker_type`, `severity`,
  `file_path`, `function_name`, `health_impact`, `details`, `reason`) — e.g.
  `complex_method`, `large_method`, `primitive_obsession`, `io_in_loop`,
  `nested_complexity`, `bumpy_road`

19 files were indexed from the worktree (mostly the Code-Geeko pilot's Python
scripts, YAML workflows, and JSON/markdown docs); `dashboard.js` was flagged as the
worst performer (score 6.0/10, CCN 139).
