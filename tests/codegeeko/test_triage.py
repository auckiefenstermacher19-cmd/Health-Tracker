import json
from unittest.mock import AsyncMock, patch

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
