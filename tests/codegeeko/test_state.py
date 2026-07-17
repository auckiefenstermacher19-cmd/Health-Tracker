import json

from codegeeko.state import (
    build_next_state,
    compute_deltas,
    load_state,
    save_state,
)

FINDING = {
    "source": "repowise",
    "file": "consolidate.py",
    "finding_id": "metric",
    "risk_score": 7.0,
    "message": "high complexity",
    "raw": {},
}

OTHER_FINDING_SAME_FILE = {
    "source": "repowise",
    "file": "consolidate.py",
    "finding_id": "run_pipeline:complex_method",
    "risk_score": 8.0,
    "message": "run_pipeline has cyclomatic complexity 40",
    "raw": {},
}

CI_FINDING = {
    "source": "ci_log",
    "file": None,
    "finding_id": "run-123",
    "risk_score": 6.0,
    "message": "consolidate workflow failed",
    "raw": {},
}


def test_compute_deltas_flags_new_finding():
    deltas = compute_deltas({"findings": {}}, [FINDING])
    assert deltas == [FINDING]


def test_compute_deltas_skips_unchanged_finding():
    key = "repowise:consolidate.py:metric"
    previous = {"findings": {key: FINDING}}
    deltas = compute_deltas(previous, [FINDING])
    assert deltas == []


def test_compute_deltas_flags_worsened_finding():
    key = "repowise:consolidate.py:metric"
    previous = {"findings": {key: {**FINDING, "risk_score": 5.0}}}
    deltas = compute_deltas(previous, [FINDING])
    assert deltas == [FINDING]


def test_compute_deltas_ignores_improved_finding():
    key = "repowise:consolidate.py:metric"
    previous = {"findings": {key: {**FINDING, "risk_score": 9.0}}}
    deltas = compute_deltas(previous, [FINDING])
    assert deltas == []


def test_build_next_state_records_checked_sources_and_findings():
    checked = {"repowise": "ok", "semgrep": "failed", "ci_log": "ok"}
    state = build_next_state([FINDING], checked)

    assert state["checked_sources"] == checked
    assert state["findings"]["repowise:consolidate.py:metric"] == FINDING


def test_build_next_state_keeps_both_findings_on_same_file():
    state = build_next_state([FINDING, OTHER_FINDING_SAME_FILE], {"repowise": "ok"})

    assert len(state["findings"]) == 2
    assert state["findings"]["repowise:consolidate.py:metric"] == FINDING
    assert state["findings"]["repowise:consolidate.py:run_pipeline:complex_method"] == OTHER_FINDING_SAME_FILE


def test_build_next_state_carries_forward_findings_from_a_failed_source():
    previous = build_next_state([CI_FINDING], {"ci_log": "ok"})

    state = build_next_state([], {"ci_log": "failed"}, previous)

    assert state["findings"]["ci_log:None:run-123"] == CI_FINDING


def test_build_next_state_drops_resolved_findings_from_a_healthy_source():
    previous = build_next_state([FINDING], {"repowise": "ok"})

    state = build_next_state([], {"repowise": "ok"}, previous)

    assert state["findings"] == {}


def test_build_next_state_carries_forward_only_the_failed_source():
    previous = build_next_state([FINDING, CI_FINDING], {"repowise": "ok", "ci_log": "ok"})

    state = build_next_state([], {"repowise": "ok", "ci_log": "failed"}, previous)

    assert "ci_log:None:run-123" in state["findings"]
    assert "repowise:consolidate.py:metric" not in state["findings"]


def test_findings_from_a_failed_source_do_not_refire_as_deltas_on_recovery():
    """Regression for the 2026-07-16 GitHub 503 outage.

    The outage made `ci_log` non-ok for six consecutive runs. `build_next_state` dropped that
    source's findings each night, so when the collector recovered it re-fired ALL of its
    historical findings as fresh deltas. Under REPORT_ONLY that was harmless (triage rejected
    them), but in fix mode that single upstream outage would have opened ~9 PRs for CI runs that
    were already fixed -- no bug in our code required, a third-party 5xx is enough.
    """
    night_one = build_next_state([CI_FINDING], {"ci_log": "ok"})
    night_two = build_next_state([], {"ci_log": "failed"}, night_one)

    recovered_deltas = compute_deltas(night_two, [CI_FINDING])

    assert recovered_deltas == []


def test_build_next_state_omits_unacted_findings_so_they_refire():
    state = build_next_state(
        [FINDING, OTHER_FINDING_SAME_FILE], {"repowise": "ok"}, None, [FINDING]
    )

    assert "repowise:consolidate.py:metric" not in state["findings"]
    assert "repowise:consolidate.py:run_pipeline:complex_method" in state["findings"]


def test_unacted_findings_are_still_deltas_on_the_next_run():
    state = build_next_state([FINDING], {"repowise": "ok"}, None, [FINDING])

    assert compute_deltas(state, [FINDING]) == [FINDING]


def test_unacted_findings_are_omitted_even_when_their_source_failed():
    """An unacted finding must always re-fire: acting on it failed, so it needs a retry.

    Carry-forward (which suppresses re-firing) must not win over the unacted exclusion, or a
    finding whose PR failed on a night its collector also flapped would be marked seen and
    silently never retried.
    """
    previous = build_next_state([CI_FINDING], {"ci_log": "ok"})

    state = build_next_state([CI_FINDING], {"ci_log": "failed"}, previous, [CI_FINDING])

    assert state["findings"] == {}


def test_load_state_returns_empty_dict_when_file_missing(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    assert load_state(str(missing)) == {"findings": {}, "checked_sources": {}}


def test_save_state_then_load_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    state = build_next_state([FINDING], {"repowise": "ok"})

    save_state(str(path), state)
    loaded = load_state(str(path))

    assert loaded == state
    assert json.loads(path.read_text()) == state
