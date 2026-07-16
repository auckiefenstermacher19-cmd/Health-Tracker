import os
import sys

from codegeeko.collectors.ci_log_collector import run_ci_log_check
from codegeeko.collectors.repowise_collector import run_repowise
from codegeeko.collectors.semgrep_collector import run_semgrep
from codegeeko.report import format_report
from codegeeko.state import build_next_state, compute_deltas, load_state, save_state
from codegeeko.triage import triage_findings

STATE_PATH = ".code-geeko/state.json"


def is_report_only(env: dict) -> bool:
    """Safe-by-default: report-only unless REPORT_ONLY is explicitly "false" (case/whitespace
    insensitive). Unset, empty, malformed, or unexpected values (e.g. "yes", "1", a stray-space
    typo, or a config templating quirk that renders as "") all stay report-only — only a
    deliberate "false" opts into the fix-enabled branch that Tasks 10/11 wire up behind this gate.
    """
    return env.get("REPORT_ONLY", "true").strip().lower() != "false"


def collect_all(repo_path: str, owner: str, repo: str, github_token: str) -> tuple[list[dict], dict[str, str]]:
    findings = []
    checked = {}

    repowise_findings, repowise_ok = run_repowise(repo_path)
    findings += repowise_findings
    checked["repowise"] = "ok" if repowise_ok else "failed"

    semgrep_findings, semgrep_ok = run_semgrep(repo_path)
    findings += semgrep_findings
    checked["semgrep"] = "ok" if semgrep_ok else "failed"

    ci_findings, ci_ok = run_ci_log_check(owner, repo, github_token)
    findings += ci_findings
    checked["ci_log"] = "ok" if ci_ok else "failed"

    return findings, checked


def main() -> None:
    """Run one nightly Code-Geeko pass: collect, diff against state, triage, report, optionally
    fix, then save state -- except on the two guarded failure paths below, where state is
    deliberately NOT saved and the process exits non-zero instead:

    1. All collectors failed (`checked` non-empty and every value != "ok"): there is zero real
       signal for the night, so we abort before paying for a triage SDK call and before
       `save_state` -- saving `build_next_state([], ...)` here would wipe the entire state file
       and re-fire every finding on recovery.
    2. Triage itself failed (`triage_ok is False` from `triage_findings`, with at least one
       delta present): a failed triage call is indistinguishable from "triage rejected
       everything" unless we keep them separate. Saving state here would permanently mark that
       night's deltas as seen, so instead we skip `save_state` and exit non-zero, letting the
       next scheduled run retry the same deltas.

    A successful triage run that legitimately accepts nothing (`triage_ok is True`, `triaged ==
    []`) is NOT a failure -- deliberate suppression is by design, and state is saved as normal.
    """
    repo_path = "."
    owner = "auckiefenstermacher19-cmd"
    repo = "Health-Tracker"
    github_token = os.environ["GITHUB_TOKEN"]
    report_only = is_report_only(os.environ)

    previous_state = load_state(STATE_PATH)
    findings, checked = collect_all(repo_path, owner, repo, github_token)

    if checked and all(status != "ok" for status in checked.values()):
        print("WARNING: all collectors failed this run -- aborting before triage; state NOT saved.")
        sys.exit(1)

    deltas = compute_deltas(previous_state, findings)
    triaged, triage_ok = triage_findings(deltas)

    print(format_report(triaged, checked))

    if report_only:
        print("\n[REPORT_ONLY=true] Skipping fix/PR step.")
    else:
        from codegeeko.fixer import fix_and_report

        for item in triaged:
            try:
                outcome = fix_and_report(item, repo_path, owner, repo, github_token)
            except Exception as exc:
                # codegeeko/fixer.py's git subprocess calls (checkout/add/commit/push/branch -D)
                # deliberately raise on failure rather than degrading gracefully like the
                # PR/Issue HTTP calls -- see fix_and_report's docstring. An unexpected local git
                # failure (e.g. a stale branch left over from a prior crashed run) signals an
                # environment problem a human should see, not something to silently launder into
                # a misleading "issue" outcome. But ONE finding's git failure must not take down
                # the whole nightly batch or skip save_state() for every other finding, so it's
                # caught here, at the per-finding boundary, and reported like any other outcome.
                print(f"  -> git_failed: {item.get('file')}/{item.get('finding_id')}: {exc}")
                continue
            detail = outcome.get("url") or outcome.get("error", "unknown")
            print(f"  -> {outcome['outcome']}: {detail}")

    if deltas and not triage_ok:
        print(f"WARNING: triage failed -- state NOT saved; {len(deltas)} delta(s) will retry tomorrow")
        sys.exit(1)

    save_state(STATE_PATH, build_next_state(findings, checked))


if __name__ == "__main__":
    main()
