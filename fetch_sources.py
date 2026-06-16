"""
fetch_sources.py
----------------
Downloads the two source CSV files from their upstream GitHub repositories:

  1. daily_consolidated.csv  ← whoop-data repo
  2. Meal_Data_Dashboard.csv ← MyFitnessClone repo

Uses the GitHub raw-content API (authenticated with GH_PAT) so that both
private repositories are accessible.  Falls back to unauthenticated requests
if GH_PAT is not set (useful for public repos or local testing).

Outputs
-------
  data/raw/daily_consolidated.csv
  data/raw/Meal_Data_Dashboard.csv

Exit codes
----------
  0 — both files fetched successfully
  1 — one or more files could not be fetched (workflow should halt)
"""

import os
import sys
import logging
import time
from pathlib import Path

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuration (override via environment variables) ────────────────────────
GH_PAT        = os.environ.get("GH_PAT", "")
GH_USERNAME   = os.environ.get("GH_USERNAME", "")      # GitHub username owning both repos

WHOOP_REPO    = os.environ.get("WHOOP_REPO",   "whoop-data")
WHOOP_BRANCH  = os.environ.get("WHOOP_BRANCH", "main")
WHOOP_PATH    = os.environ.get("WHOOP_PATH",   "data/daily_consolidated.csv")

MEAL_REPO     = os.environ.get("MEAL_REPO",    "MyFitnessClone")
MEAL_BRANCH   = os.environ.get("MEAL_BRANCH",  "main")
MEAL_PATH     = os.environ.get("MEAL_PATH",    "Meal_Data_Dashboard.csv")

RAW_DIR       = Path("raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

RETRY_ATTEMPTS = 3
RETRY_DELAY    = 10   # seconds between retries


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers() -> dict:
    """Build request headers, injecting auth token when available."""
    h = {"Accept": "application/vnd.github.v3.raw"}
    if GH_PAT:
        h["Authorization"] = f"Bearer {GH_PAT}"
    return h


def _raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    """Construct the GitHub raw-content API URL for a file."""
    return (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/contents/{path}?ref={branch}"
    )


def fetch_file(
    owner: str,
    repo: str,
    branch: str,
    remote_path: str,
    local_path: Path,
    label: str,
) -> bool:
    """
    Download a single file from GitHub and write it to local_path.

    Parameters
    ----------
    owner       : GitHub username / org that owns the repo
    repo        : repository name
    branch      : branch name (e.g. "main")
    remote_path : path within the repo (e.g. "data/daily_consolidated.csv")
    local_path  : where to save the file locally
    label       : human-readable name used in log messages

    Returns
    -------
    True if the file was fetched and written successfully, False otherwise.
    """
    url = _raw_url(owner, repo, branch, remote_path)
    log.info("[%s] Fetching from %s/%s @ %s  →  %s", label, repo, remote_path, branch, local_path)

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=_headers(), timeout=30)

            if resp.status_code == 404:
                log.error(
                    "[%s] 404 Not Found — check REPO/BRANCH/PATH configuration.\n"
                    "  URL attempted: %s",
                    label, url,
                )
                return False

            if resp.status_code == 401:
                log.error(
                    "[%s] 401 Unauthorized — verify GH_PAT is set and has 'Contents: read' "
                    "permission for repo '%s'.",
                    label, repo,
                )
                return False

            if resp.status_code == 403:
                log.error(
                    "[%s] 403 Forbidden — GH_PAT may lack permission for repo '%s', "
                    "or rate limit exceeded.",
                    label, repo,
                )
                return False

            resp.raise_for_status()

        except requests.exceptions.Timeout:
            log.warning("[%s] Attempt %d/%d timed out. Retrying in %ds…",
                        label, attempt, RETRY_ATTEMPTS, RETRY_DELAY)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
                continue
            log.error("[%s] All %d attempts timed out.", label, RETRY_ATTEMPTS)
            return False

        except requests.exceptions.RequestException as exc:
            log.warning("[%s] Attempt %d/%d failed: %s", label, attempt, RETRY_ATTEMPTS, exc)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
                continue
            log.error("[%s] All %d attempts failed.", label, RETRY_ATTEMPTS)
            return False

        # Success — write file
        content = resp.content
        local_path.write_bytes(content)

        size_kb = len(content) / 1024
        # Quick sanity-check: the file should look like a CSV (has commas)
        if b"," not in content[:1024]:
            log.warning(
                "[%s] Downloaded content does not appear to be a CSV "
                "(no comma in first 1024 bytes). Proceeding anyway.",
                label,
            )

        log.info("[%s] ✓  Saved  %s  (%.1f KB)", label, local_path, size_kb)
        return True

    return False   # unreachable, but satisfies type checkers


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 60)
    log.info("  Health Tracker — Source Fetch")
    log.info("=" * 60)

    if not GH_USERNAME:
        log.error(
            "GH_USERNAME environment variable is not set.\n"
            "Set it to the GitHub username or org that owns both source repos."
        )
        sys.exit(1)

    if not GH_PAT:
        log.warning(
            "GH_PAT is not set — requests will be unauthenticated. "
            "This will fail for private repositories and is rate-limited "
            "(60 requests/hour) for public ones."
        )

    sources = [
        {
            "label":       "WHOOP daily_consolidated",
            "owner":       GH_USERNAME,
            "repo":        WHOOP_REPO,
            "branch":      WHOOP_BRANCH,
            "remote_path": WHOOP_PATH,
            "local_path":  RAW_DIR / "daily_consolidated.csv",
        },
        {
            "label":       "Meal_Data_Dashboard",
            "owner":       GH_USERNAME,
            "repo":        MEAL_REPO,
            "branch":      MEAL_BRANCH,
            "remote_path": MEAL_PATH,
            "local_path":  RAW_DIR / "Meal_Data_Dashboard.csv",
        },
    ]

    failures = []
    for src in sources:
        ok = fetch_file(
            owner       = src["owner"],
            repo        = src["repo"],
            branch      = src["branch"],
            remote_path = src["remote_path"],
            local_path  = src["local_path"],
            label       = src["label"],
        )
        if not ok:
            failures.append(src["label"])

    log.info("-" * 60)
    if failures:
        log.error("FETCH FAILED for: %s", ", ".join(failures))
        log.error("Consolidation cannot proceed. Fix the issues above and re-run.")
        sys.exit(1)

    log.info("All source files fetched successfully.")
    log.info("  %s", RAW_DIR / "daily_consolidated.csv")
    log.info("  %s", RAW_DIR / "Meal_Data_Dashboard.csv")


if __name__ == "__main__":
    main()
