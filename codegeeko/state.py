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


def build_next_state(current_findings: list[dict], checked_sources: dict[str, str]) -> dict:
    return {
        "findings": {_key(f): f for f in current_findings},
        "checked_sources": checked_sources,
    }
