import json
import subprocess

# Biomarker severity -> 0-10 risk_score. Repowise's `findings` entries carry a categorical
# severity (not a numeric score), so we bucket it onto Code-Geeko's 0-10 scale.
_SEVERITY_TO_RISK = {
    "critical": 10.0,
    "high": 7.5,
    "medium": 5.0,
    "low": 2.5,
}

# A file's raw `score` in raw["metrics"] is already 0-10, but healthier = higher (opposite of
# Code-Geeko's risk_score convention), so we invert it: risk_score = 10.0 - score.
_PERFECT_SCORE = 10.0

# Severity rank used only to pick a deterministic representative item out of a group of
# duplicates (see _pick_representative) — higher rank = worse = preferred as the representative.
_SEVERITY_RANK = {
    "critical": 3,
    "high": 2,
    "medium": 1,
    "low": 0,
}


def _pick_representative(items: list[dict]) -> dict:
    """Deterministically pick one item out of a group of duplicates, independent of the order
    they appeared in raw["findings"] (that order is not documented as stable across repowise
    runs, and Task 6 persists state keyed on the resulting finding, so a flip-flopping payload
    would be as bad as a flip-flopping finding_id). Prefer the worst (highest-ranked) severity;
    break ties with the item's own sorted-key JSON serialization, which gives a total order even
    when two items are genuinely field-identical.
    """
    return sorted(
        items,
        key=lambda it: (
            -_SEVERITY_RANK.get(it.get("severity"), -1),
            json.dumps(it, sort_keys=True),
        ),
    )[0]


def parse_repowise_output(raw: dict) -> list[dict]:
    """Normalize a `repowise health --format json` payload into Code-Geeko findings.

    The real fixture (tests/codegeeko/fixtures/repowise_sample_output.json) has three
    top-level keys: `kpis` (aggregate, not per-file, so unused here), `metrics` (one entry
    per analyzed file with an overall 0-10 health `score`), and `findings` (specific
    code-health biomarkers such as complex_method/bumpy_road/io_in_loop tied to a
    file_path + function_name). Both `metrics` and `findings` are normalized here:

    - `metrics`: files scoring below a perfect 10.0 become one finding each (a perfect
      score has nothing to report, so it's skipped rather than emitting 0-risk noise).
    - `findings`: each distinct (file, function, biomarker_type) becomes one finding — this
      is the specific, actionable signal (e.g. "renderDay has cyclomatic complexity 139").

    `finding_id` uniquely identifies a finding within a given `file` (state/triage/PR tasks
    key dedup by `f"{source}:{file}:{finding_id}"`, per Code-Geeko plan amendment e52cbbd).
    There is at most one metrics entry per file, so `"metric"` alone is unique there.
    `findings` entries are id'd by `function_name:biomarker_type` — a content-derived key, not
    a list-position-derived one, because `raw["findings"]`'s order is not documented anywhere
    as stable across repowise runs. The real fixture proves that `(function_name,
    biomarker_type)` pair is NOT always unique within a file — dashboard.js's `buildCoaching`
    has two field-identical `complex_conditional` entries with no other distinguishing data
    (verified against tests/codegeeko/fixtures/repowise_sample_output.json). Since there is no
    ordering-independent way to tell such duplicates apart, they are collapsed into a single
    finding rather than positionally numbered — the occurrence count is noted in `message`
    instead, so `finding_id` never depends on list position.
    """
    findings = []

    # Group metrics entries by file_path first. The real fixture always has at most one metrics
    # entry per file (verified programmatically), but this guards against a future payload that
    # ever has duplicates: pick the worst (lowest) score deterministically via _pick_representative
    # rather than emitting one finding_id="metric" per duplicate (which would collide) or picking
    # whichever entry happened to be first in the list.
    metrics_groups: dict[str, list[dict]] = {}
    for item in raw.get("metrics", []):
        file_path = item.get("file_path")
        if file_path is None or item.get("score") is None:
            continue
        metrics_groups.setdefault(file_path, []).append(item)

    for file_path, items in metrics_groups.items():
        item = min(items, key=lambda it: (it["score"], json.dumps(it, sort_keys=True)))
        score = item["score"]
        if score >= _PERFECT_SCORE:
            continue
        risk_score = max(0.0, min(10.0, _PERFECT_SCORE - float(score)))
        findings.append({
            "source": "repowise",
            "file": file_path,
            "finding_id": "metric",
            "risk_score": round(risk_score, 2),
            "message": (
                f"overall file health score {score}/10 "
                f"(max CCN {item.get('max_ccn')}, max nesting {item.get('max_nesting')})"
            ),
            "raw": item,
        })

    # Group findings entries by (file_path, function_name, biomarker_type) so that
    # duplicates collapse into one finding with a content-derived finding_id, instead of being
    # numbered by their (unstable) position in raw["findings"].
    groups: dict[tuple, list[dict]] = {}
    for item in raw.get("findings", []):
        file_path = item.get("file_path")
        if file_path is None:
            continue
        group_key = (file_path, item.get("function_name"), item.get("biomarker_type"))
        groups.setdefault(group_key, []).append(item)

    for (file_path, function_name, biomarker_type), items in groups.items():
        # The representative must be chosen deterministically, not via items[0] — grouping only
        # guarantees matching (file_path, function_name, biomarker_type), not that every member
        # has the same severity/reason/raw payload. An order-dependent pick would let the
        # attached risk_score/message flip between runs even though finding_id stays stable,
        # which defeats Task 6's (file, finding_id)-keyed change detection just as badly as an
        # unstable finding_id would.
        item = _pick_representative(items)
        occurrences = len(items)
        risk_score = _SEVERITY_TO_RISK.get(item.get("severity"), 5.0)
        message = item.get("reason", f"{biomarker_type} detected")
        if occurrences > 1:
            message = f"{message} (occurs {occurrences} times)"
        findings.append({
            "source": "repowise",
            "file": file_path,
            "finding_id": f"{function_name}:{biomarker_type}",
            "risk_score": risk_score,
            "message": message,
            "raw": item,
        })

    return findings


def run_repowise(repo_path: str) -> tuple[list[dict], bool]:
    """Run repowise against repo_path and return normalized findings.

    Note: `repowise export --format json` does not work after `repowise init --index-only`
    (it only exports LLM-generated wiki pages, which --index-only skips — see
    tests/codegeeko/fixtures/repowise_sample_output.md for the captured failure). We use
    `repowise health --format json` instead, which runs in-process off the index with no
    LLM/network calls and is what actually produced the real fixture.
    """
    try:
        subprocess.run(
            ["repowise", "init", ".", "--index-only"],
            check=True, capture_output=True, timeout=120, cwd=repo_path,
        )
        result = subprocess.run(
            ["repowise", "health", "--format", "json"],
            check=True, capture_output=True, timeout=60, cwd=repo_path, text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return [], False

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], False
    return parse_repowise_output(raw), True
