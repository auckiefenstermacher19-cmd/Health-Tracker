"""
generate_audit_report.py
------------------------
Reads logs/consolidation_audit.jsonl and generates a human-readable
Markdown summary appended to logs/audit_report.md.

Run automatically at the end of the consolidation workflow, or on demand:
    python scripts/generate_audit_report.py

This file is committed to the repo so there is always a human-readable
record of every consolidation run — useful for debugging and compliance.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR          = Path("logs")
AUDIT_JSONL      = LOG_DIR / "consolidation_audit.jsonl"
AUDIT_REPORT_MD  = LOG_DIR / "audit_report.md"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_audit_records() -> list[dict]:
    """Load all JSONL audit records, newest-first."""
    if not AUDIT_JSONL.exists():
        return []
    records = []
    with open(AUDIT_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Skipping malformed audit record: %s", line[:80])
    return list(reversed(records))   # newest first


def format_record(r: dict, idx: int) -> str:
    """Format a single audit record as a Markdown section."""
    run_at   = r.get("run_at",  "unknown")
    status   = r.get("status",  "UNKNOWN")
    rows     = r.get("total_rows", "?")
    cols     = r.get("total_cols", "?")
    duration = r.get("duration_seconds", "?")
    w_range  = r.get("whoop_date_range", [])
    m_range  = r.get("meal_date_range",  [])
    overlap  = r.get("overlap_dates", "?")
    w_only   = r.get("whoop_only_dates", "?")
    m_only   = r.get("meal_only_dates",  "?")
    w_cols   = r.get("whoop_cols", "?")
    m_cols   = r.get("meal_cols",  "?")

    status_icon = "✅" if status == "SUCCESS" else "❌"

    w_range_str = f"{w_range[0]} → {w_range[1]}" if len(w_range) == 2 else "N/A"
    m_range_str = f"{m_range[0]} → {m_range[1]}" if len(m_range) == 2 else "N/A"

    return f"""
### Run #{idx + 1} — {run_at[:19].replace("T", " ")} UTC  {status_icon}

| Metric | Value |
|---|---|
| Status | **{status}** |
| Duration | {duration}s |
| Output rows | {rows} |
| Output columns | {cols} |
| WHOOP columns | {w_cols} |
| Meal columns | {m_cols} |
| WHOOP date range | {w_range_str} |
| Meal date range | {m_range_str} |
| Overlapping dates | {overlap} |
| WHOOP-only dates | {w_only} |
| Meal-only dates | {m_only} |
"""


def main() -> None:
    records = load_audit_records()

    if not records:
        log.info("No audit records found at %s. Nothing to report.", AUDIT_JSONL)
        sys.exit(0)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Health Tracker — Consolidation Audit Report",
        f"",
        f"*Generated: {now}*  |  *{len(records)} run(s) recorded*",
        f"",
        f"---",
    ]

    for i, record in enumerate(records[:50]):   # cap at 50 most recent
        lines.append(format_record(record, i))

    if len(records) > 50:
        lines.append(f"\n> *… {len(records) - 50} older run(s) not shown. See `{AUDIT_JSONL}` for full history.*\n")

    AUDIT_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    log.info("Audit report written → %s  (%d run(s))", AUDIT_REPORT_MD, len(records))


if __name__ == "__main__":
    main()
