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
