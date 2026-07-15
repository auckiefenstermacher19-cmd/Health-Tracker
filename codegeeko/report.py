def format_report(triaged: list[dict], checked_sources: dict[str, str]) -> str:
    lines = ["# Code-Geeko Nightly Report", ""]

    failed = [source for source, status in checked_sources.items() if status != "ok"]
    if failed:
        lines.append(f"**Collectors that failed this run:** {', '.join(failed)}")
        lines.append("")

    if not triaged:
        lines.append("No new or worsened findings accepted for action tonight.")
        return "\n".join(lines)

    lines.append(f"**{len(triaged)} finding(s) accepted for action:**")
    lines.append("")
    for item in triaged:
        lines.append(f"- **{item['file']}** ({item['source']}, risk {item['risk_score']}): {item['message']}")
        lines.append(f"  - Why: {item['triage_reason']}")

    return "\n".join(lines)
