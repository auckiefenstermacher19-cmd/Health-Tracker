import asyncio
import json
from unittest.mock import patch

import pytest

from codegeeko.triage import triage_findings

DELTA = {"source": "repowise", "file": "consolidate.py", "finding_id": "metric", "risk_score": 8.0, "message": "high complexity", "raw": {}}


class _FakeResultMessage:
    subtype = "success"
    result = json.dumps({"decisions": [{"file": "consolidate.py", "finding_id": "metric", "accept": True, "reason": "clear fix available"}]})


async def _fake_query(*args, **kwargs):
    yield _FakeResultMessage()


def test_triage_findings_keeps_accepted_items_with_reason():
    with patch("codegeeko.triage.query", _fake_query):
        result = triage_findings([DELTA])

    assert len(result) == 1
    assert result[0]["file"] == "consolidate.py"
    assert result[0]["triage_reason"] == "clear fix available"


def test_triage_findings_drops_rejected_items():
    class _RejectResultMessage:
        subtype = "success"
        result = json.dumps({"decisions": [{"file": "consolidate.py", "finding_id": "metric", "accept": False, "reason": "not worth it"}]})

    async def _fake_reject_query(*args, **kwargs):
        yield _RejectResultMessage()

    with patch("codegeeko.triage.query", _fake_reject_query):
        result = triage_findings([DELTA])

    assert result == []


def test_triage_findings_matches_decisions_by_file_and_finding_id_not_file_alone():
    # Two different findings on the SAME file must be triaged independently — matching by
    # `file` alone would collapse them onto one decision (the bug this test guards against).
    delta_a = {"source": "repowise", "file": "dashboard.js", "finding_id": "renderDay:complex_method", "risk_score": 9.0, "message": "renderDay too complex", "raw": {}}
    delta_b = {"source": "repowise", "file": "dashboard.js", "finding_id": "metric", "risk_score": 4.0, "message": "overall file health", "raw": {}}

    class _MixedResultMessage:
        subtype = "success"
        result = json.dumps({"decisions": [
            {"file": "dashboard.js", "finding_id": "renderDay:complex_method", "accept": True, "reason": "worth fixing"},
            {"file": "dashboard.js", "finding_id": "metric", "accept": False, "reason": "too broad to auto-fix"},
        ]})

    async def _fake_mixed_query(*args, **kwargs):
        yield _MixedResultMessage()

    with patch("codegeeko.triage.query", _fake_mixed_query):
        result = triage_findings([delta_a, delta_b])

    assert len(result) == 1
    assert result[0]["finding_id"] == "renderDay:complex_method"


def test_triage_findings_handles_empty_deltas_without_calling_sdk():
    with patch("codegeeko.triage.query") as mock_query:
        result = triage_findings([])

    assert result == []
    mock_query.assert_not_called()


def test_triage_findings_degrades_gracefully_on_malformed_sdk_response():
    # The SDK returning non-JSON must not raise out of triage_findings and crash the nightly
    # run — it should degrade to "no decisions", same as the sibling collectors' fail-closed
    # pattern for malformed external I/O (e.g. repowise_collector's `except
    # json.JSONDecodeError: return [], False`).
    class _MalformedResultMessage:
        subtype = "success"
        result = "not valid json{"

    async def _fake_malformed_query(*args, **kwargs):
        yield _MalformedResultMessage()

    with patch("codegeeko.triage.query", _fake_malformed_query):
        result = triage_findings([DELTA])

    assert result == []


def test_triage_findings_degrades_gracefully_when_decision_missing_keys():
    # A decision missing "file"/"finding_id" must not raise during _decision_key indexing — it
    # should be skipped, and any other findings with no matching (well-formed) decision are
    # dropped too (fail-closed: not accepted).
    class _MissingKeyResultMessage:
        subtype = "success"
        result = json.dumps({"decisions": [{"accept": True, "reason": "malformed decision, no file/finding_id"}]})

    async def _fake_missing_key_query(*args, **kwargs):
        yield _MissingKeyResultMessage()

    with patch("codegeeko.triage.query", _fake_missing_key_query):
        result = triage_findings([DELTA])

    assert result == []


@pytest.mark.parametrize("raw_result", ["[1, 2, 3]", "null", '"oops"', "42"])
def test_triage_findings_degrades_gracefully_when_top_level_json_is_not_a_dict(raw_result):
    # Syntactically valid JSON that isn't a dict (list/null/string/number all parse fine via
    # json.loads) must not raise AttributeError from `parsed.get(...)` — it should degrade to
    # "no decisions", same as any other malformed external response.
    class _NonDictResultMessage:
        subtype = "success"
        result = raw_result

    async def _fake_non_dict_query(*args, **kwargs):
        yield _NonDictResultMessage()

    with patch("codegeeko.triage.query", _fake_non_dict_query):
        result = triage_findings([DELTA])

    assert result == []


def test_triage_findings_degrades_gracefully_when_decisions_value_is_null():
    # {"decisions": null} is a plausible "nothing to report" shape from an LLM. dict.get's
    # default only fires when the key is absent, not when the value is explicitly None, so
    # this must not raise TypeError from `for item in None`.
    class _NullDecisionsResultMessage:
        subtype = "success"
        result = json.dumps({"decisions": None})

    async def _fake_null_decisions_query(*args, **kwargs):
        yield _NullDecisionsResultMessage()

    with patch("codegeeko.triage.query", _fake_null_decisions_query):
        result = triage_findings([DELTA])

    assert result == []


def test_triage_findings_degrades_gracefully_on_timeout():
    # A stalled/hung SDK call must not hang the whole nightly run — it should degrade to "no
    # decisions" once the timeout in _run_triage_query fires, same as every other time-bounded
    # external call in this codebase. Uses a genuinely slow fake `query` plus a shortened
    # timeout (rather than mocking asyncio.wait_for directly) so asyncio.wait_for cancels the
    # in-flight coroutine the normal way instead of leaving it dangling un-awaited.
    async def _slow_query(*args, **kwargs):
        await asyncio.sleep(0.3)
        yield _FakeResultMessage()

    with (
        patch("codegeeko.triage.query", _slow_query),
        patch("codegeeko.triage._TRIAGE_TIMEOUT_SECONDS", 0.05),
    ):
        result = triage_findings([DELTA])

    assert result == []
