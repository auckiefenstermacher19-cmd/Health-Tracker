import os

from codegeeko.collectors.ci_log_collector import run_ci_log_check
from codegeeko.collectors.repowise_collector import run_repowise
from codegeeko.collectors.semgrep_collector import run_semgrep
from codegeeko.state import build_next_state, compute_deltas, load_state, save_state

STATE_PATH = ".code-geeko/state.json"


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
    repo_path = "."
    owner = "auckiefenstermacher19-cmd"
    repo = "Health-Tracker"
    github_token = os.environ["GITHUB_TOKEN"]

    previous_state = load_state(STATE_PATH)
    findings, checked = collect_all(repo_path, owner, repo, github_token)
    deltas = compute_deltas(previous_state, findings)

    print(f"Collected {len(findings)} findings ({checked}). {len(deltas)} new-or-worsened.")
    for delta in deltas:
        print(f"  [{delta['source']}] {delta['file']}: {delta['message']} (risk {delta['risk_score']})")

    save_state(STATE_PATH, build_next_state(findings, checked))


if __name__ == "__main__":
    main()
