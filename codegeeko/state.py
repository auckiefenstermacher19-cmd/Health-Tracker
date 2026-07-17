import json
import os


def _key(finding: dict) -> str:
    return f"{finding['source']}:{finding['file']}:{finding['finding_id']}"


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"findings": {}, "checked_sources": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def compute_deltas(previous_state: dict, current_findings: list[dict]) -> list[dict]:
    previous_findings = previous_state.get("findings", {})
    deltas = []
    for finding in current_findings:
        previous = previous_findings.get(_key(finding))
        if previous is None or finding["risk_score"] > previous["risk_score"]:
            deltas.append(finding)
    return deltas


def build_next_state(
    current_findings: list[dict],
    checked_sources: dict[str, str],
    previous_state: dict | None = None,
    unacted_findings: list[dict] | None = None,
) -> dict:
    """Build the state to persist after a run, separating "we collected it" from "we acted on it".

    Two adjustments keep a finding out of, or back in, the "already seen" set:

    `previous_state` drives CARRY-FORWARD. A source that did not report "ok" this run collected
    nothing (or only part of its set), so its previous findings are carried forward rather than
    dropped. Without this, a one-night collector flap re-fires that source's entire finding set as
    fresh deltas on recovery. This is not theoretical: a ~77-minute GitHub 503 outage on 2026-07-16
    made `ci_log` non-ok for six consecutive runs, and on recovery all 9 of its historical findings
    re-fired at once. Under REPORT_ONLY triage rejected them; in fix mode that single upstream
    outage would have opened ~9 PRs for CI runs that were already fixed. A third-party 5xx is
    sufficient to trigger it -- no bug of ours is required -- and the collector's retry only
    shortens the window rather than closing it.

    `unacted_findings` drives EXCLUSION, and is applied AFTER carry-forward so it always wins. It
    holds findings triage accepted but the run did not successfully act on: deferred past the
    per-night fix cap, or whose PR/Issue/git step failed. Omitting them from state means they
    re-delta and get retried on the next run, instead of being marked seen and silently dropped
    forever -- the same swallow class Task 11.5 guarded against for triage failures.
    """
    findings = {_key(f): f for f in current_findings}

    previous_findings = (previous_state or {}).get("findings", {})
    failed_sources = {s for s, status in checked_sources.items() if status != "ok"}
    for key, finding in previous_findings.items():
        if finding["source"] in failed_sources:
            findings.setdefault(key, finding)

    for finding in unacted_findings or []:
        findings.pop(_key(finding), None)

    return {
        "findings": findings,
        "checked_sources": checked_sources,
    }
