import asyncio
import json

from claude_agent_sdk import ClaudeAgentOptions, query

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


def _run_triage_query(deltas: list[dict]) -> dict:
    options = ClaudeAgentOptions(model="claude-sonnet-5", allowed_tools=[])
    prompt = _TRIAGE_PROMPT_TEMPLATE.format(
        findings_json=json.dumps([{"file": d["file"], "finding_id": d["finding_id"], "source": d["source"], "message": d["message"], "risk_score": d["risk_score"]} for d in deltas])
    )

    async def _collect():
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "subtype", None) == "success":
                return json.loads(message.result)
        return {"decisions": []}

    return asyncio.run(_collect())


def _decision_key(item: dict) -> tuple:
    return (item["file"], item["finding_id"])


def triage_findings(deltas: list[dict]) -> list[dict]:
    if not deltas:
        return []

    response = _run_triage_query(deltas)
    decisions_by_key = {_decision_key(d): d for d in response.get("decisions", [])}

    accepted = []
    for delta in deltas:
        decision = decisions_by_key.get(_decision_key(delta))
        if decision and decision.get("accept"):
            accepted.append({**delta, "triage_reason": decision.get("reason", "")})
    return accepted
