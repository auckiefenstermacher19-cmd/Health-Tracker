import asyncio
import json

from claude_agent_sdk import ClaudeAgentOptions, query

# Every other external I/O call in this codebase is time-bounded (subprocess.run(...,
# timeout=...), requests.get(..., timeout=30)) so one flaky dependency can't hang the whole
# nightly run. This is triage, not a long-running fix, so keep it well under a minute-and-a-half.
_TRIAGE_TIMEOUT_SECONDS = 90

_TRIAGE_PROMPT_TEMPLATE = """You are triaging code health findings for a small repo. Multiple \
findings can share the same file — treat each one as an independent decision keyed by its \
finding_id, do not merge or deduplicate findings that share a file. For each finding below, \
decide whether it is worth fixing automatically tonight (accept=true) or should be skipped \
(accept=false) — skip anything cosmetic, anything requiring a design decision only a human \
should make, or anything you're not confident you can fix safely in isolation.

Findings:
{findings_json}

Respond with ONLY a JSON object: {{"decisions": [{{"file": "<file>", "finding_id": \
"<finding_id>", "accept": true|false, "reason": "<one sentence>"}}, ...]}}, one decision per \
finding, in the same order."""


def _decision_key(item: dict) -> tuple:
    return (item["file"], item["finding_id"])


def _run_triage_query(deltas: list[dict]) -> dict:
    """Ask Claude to triage `deltas` and return a `{(file, finding_id): decision}` lookup.

    Fail-closed, mirroring the pattern every sibling collector already uses for external I/O
    (repowise_collector.py / semgrep_collector.py: `except json.JSONDecodeError: return [],
    False`; ci_log_collector.py: `except requests.RequestException: return [], False`). Every
    failure mode here — a stalled/hung SDK call, no success message ever seen, a non-JSON
    response, or a decision missing "file"/"finding_id" — collapses to the same outcome: an
    empty lookup, i.e. "no decisions", so a bad external response degrades gracefully instead of
    raising out of `triage_findings` and crashing the whole nightly run.
    """
    options = ClaudeAgentOptions(model="claude-sonnet-5", allowed_tools=[])
    prompt = _TRIAGE_PROMPT_TEMPLATE.format(
        findings_json=json.dumps([{"file": d["file"], "finding_id": d["finding_id"], "source": d["source"], "message": d["message"], "risk_score": d["risk_score"]} for d in deltas])
    )

    async def _collect():
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "subtype", None) == "success":
                return message.result
        return None

    try:
        raw_result = asyncio.run(asyncio.wait_for(_collect(), timeout=_TRIAGE_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        return {}

    if raw_result is None:
        return {}

    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return {}

    decisions_by_key = {}
    for item in parsed.get("decisions", []):
        try:
            decisions_by_key[_decision_key(item)] = item
        except (KeyError, TypeError):
            continue
    return decisions_by_key


def triage_findings(deltas: list[dict]) -> list[dict]:
    if not deltas:
        return []

    decisions_by_key = _run_triage_query(deltas)

    accepted = []
    for delta in deltas:
        decision = decisions_by_key.get(_decision_key(delta))
        if decision and decision.get("accept"):
            accepted.append({**delta, "triage_reason": decision.get("reason", "")})
    return accepted
