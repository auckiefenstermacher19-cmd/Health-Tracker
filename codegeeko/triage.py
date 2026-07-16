import asyncio
import json

from claude_agent_sdk import ClaudeAgentOptions, query

# Every other external I/O call in this codebase is time-bounded (subprocess.run(...,
# timeout=...), requests.get(..., timeout=30)) so one flaky dependency can't hang the whole
# nightly run. 300s (not the original 90s) because the very first real run sends the largest
# batch this pilot will ever send -- every existing finding is a delta against empty state, and a
# too-tight timeout risks feeding the exact triage-failure path Task 11.5 closes off.
_TRIAGE_TIMEOUT_SECONDS = 300

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


def _run_triage_query(deltas: list[dict]) -> dict | None:
    """Ask Claude to triage `deltas` and return a `{(file, finding_id): decision}` lookup, or
    `None` if the triage call itself failed.

    Mirrors the fail-closed pattern every sibling collector already uses for external I/O
    (repowise_collector.py / semgrep_collector.py: `except json.JSONDecodeError: return [],
    False`; ci_log_collector.py: `except requests.RequestException: return [], False`) -- but with
    a critical distinction from earlier versions of this function: a FAILURE of the triage call
    itself (a stalled/hung SDK call, any other exception raised by the SDK's async generator --
    CLI process failing to spawn, exiting non-zero, a broken pipe, an auth/config error, etc.,
    since this call is the trust boundary between our code and an external subprocess/API we
    don't control -- no success message ever seen, a success message missing "result", a non-JSON
    response, or a syntactically-valid-but-structurally-wrong response, e.g. `[1, 2, 3]`, `null`,
    `{"decisions": null}`) returns `None`, NOT `{}`. `None` is the caller's (`triage_findings`)
    signal that triage did not actually run to completion, as opposed to a well-formed decisions
    list that happens to be empty or that legitimately rejects every finding -- those are real
    successes and return a (possibly empty) dict. A single malformed decision *within* an
    otherwise well-formed decisions list (missing "file"/"finding_id") is not a call failure: that
    one decision is skipped and the rest of the (possibly still-empty) dict is returned normally.
    Collapsing "the call failed" and "the call succeeded and said no" into the same return value
    is exactly the bug this distinction exists to prevent -- see `triage_findings` and
    `run.py::main` for how `None` propagates into a loud, non-destructive failure.
    """
    options = ClaudeAgentOptions(model="claude-sonnet-5", allowed_tools=[])
    prompt = _TRIAGE_PROMPT_TEMPLATE.format(
        findings_json=json.dumps([{"file": d["file"], "finding_id": d["finding_id"], "source": d["source"], "message": d["message"], "risk_score": d["risk_score"]} for d in deltas])
    )

    async def _collect():
        # Capture the success result but DRAIN the generator to completion -- do NOT `return`
        # mid-iteration. An early return leaves query()'s async generator open; under the
        # asyncio.wait_for() below, its teardown races the wait_for cancel scope and raises
        # `RuntimeError: aclose(): asynchronous generator is already running`, which the broad
        # `except Exception` then (mis)reads as a triage failure. The workflow's smoke step drains
        # fully for exactly this reason. The ResultMessage(subtype="success") is terminal, so the
        # loop ends right after it anyway -- draining to the end is free.
        result = None
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "subtype", None) == "success":
                result = getattr(message, "result", None)
        return result

    try:
        raw_result = asyncio.run(asyncio.wait_for(_collect(), timeout=_TRIAGE_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        return None
    except Exception:
        # Broad catch is deliberate here: this is the external trust boundary (subprocess/API we
        # don't control), and every other failure mode in this function already degrades to the
        # same "triage call failed" outcome (None) rather than propagating.
        return None

    if raw_result is None:
        # No message with subtype "success" was ever seen, or one was seen but carried no
        # "result" -- either way we never got a decisions payload.
        return None

    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return None

    # `parsed` can be *syntactically* valid JSON while structurally nothing like the expected
    # `{"decisions": [...]}` shape — e.g. `[1, 2, 3]`, `null`, `"oops"`, or `42` all parse fine
    # via json.loads but aren't dicts (no `.get`), and `{"decisions": null}` is a plausible
    # "nothing to report" shape from an LLM where `.get("decisions", [])` still returns `None`
    # (the `[]` default only fires when the key is absent, not when its value is explicitly
    # None). Either shape means we never got a well-formed decisions list, so it's a call
    # failure (None) -- NOT a legitimate "zero decisions" success -- otherwise a garbled response
    # would be indistinguishable from "triage looked at everything and said no".
    decisions = parsed.get("decisions") if isinstance(parsed, dict) else None
    if not isinstance(decisions, list):
        return None

    decisions_by_key = {}
    for item in decisions:
        try:
            decisions_by_key[_decision_key(item)] = item
        except (KeyError, TypeError):
            # One malformed decision inside an otherwise well-formed list doesn't invalidate the
            # whole call -- skip it. The matching finding below just won't find a decision for
            # its key and stays unaccepted.
            continue
    return decisions_by_key


def triage_findings(deltas: list[dict]) -> tuple[list[dict], bool]:
    """Triage `deltas` and return `(accepted, triage_ok)`.

    `triage_ok` is False ONLY when the triage call itself failed (see `_run_triage_query`'s
    docstring for the full list of failure modes) -- never when it succeeded and legitimately
    decided to accept nothing. That distinction is load-bearing for the caller (`run.py::main`):
    on `triage_ok is False` it must print a loud warning, exit non-zero, and skip `save_state` so
    the untouched deltas retry tomorrow, instead of silently marking a failed night's findings as
    seen forever. Empty `deltas` is trivially `([], True)` with no SDK call at all -- there is
    nothing to fail at.
    """
    if not deltas:
        return [], True

    decisions_by_key = _run_triage_query(deltas)
    if decisions_by_key is None:
        return [], False

    accepted = []
    for delta in deltas:
        decision = decisions_by_key.get(_decision_key(delta))
        if decision and decision.get("accept"):
            accepted.append({**delta, "triage_reason": decision.get("reason", "")})
    return accepted, True
