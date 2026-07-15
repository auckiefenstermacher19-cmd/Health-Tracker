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


def parse_repowise_output(raw: dict) -> list[dict]:
    """Normalize a `repowise health --format json` payload into Code-Geeko findings.

    The real fixture (tests/codegeeko/fixtures/repowise_sample_output.json) has three
    top-level keys: `kpis` (aggregate, not per-file, so unused here), `metrics` (one entry
    per analyzed file with an overall 0-10 health `score`), and `findings` (specific
    code-health biomarkers such as complex_method/bumpy_road/io_in_loop tied to a
    file_path + function_name). Both `metrics` and `findings` are normalized here:

    - `metrics`: files scoring below a perfect 10.0 become one finding each (a perfect
      score has nothing to report, so it's skipped rather than emitting 0-risk noise).
    - `findings`: every biomarker becomes one finding — this is the specific, actionable
      signal (e.g. "renderDay has cyclomatic complexity 139").
    """
    findings = []

    for item in raw.get("metrics", []):
        score = item.get("score")
        if score is None or score >= _PERFECT_SCORE:
            continue
        findings.append({
            "source": "repowise",
            "file": item["file_path"],
            "risk_score": round(_PERFECT_SCORE - float(score), 2),
            "message": (
                f"overall file health score {score}/10 "
                f"(max CCN {item.get('max_ccn')}, max nesting {item.get('max_nesting')})"
            ),
            "raw": item,
        })

    for item in raw.get("findings", []):
        risk_score = _SEVERITY_TO_RISK.get(item.get("severity"), 5.0)
        findings.append({
            "source": "repowise",
            "file": item["file_path"],
            "risk_score": risk_score,
            "message": item.get("reason", f"{item.get('biomarker_type')} detected"),
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
