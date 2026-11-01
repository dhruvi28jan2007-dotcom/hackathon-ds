import json
from datetime import datetime, timezone
from backend.models import InvestigationResult


def generate_json_passport(result: InvestigationResult) -> str:
    """
    Generate standard formatted JSON Evidence Passport.
    """
    return result.model_dump_json(indent=2)


def generate_markdown_passport(
    result: InvestigationResult,
    model_name: str = "Open-Weight Model",
) -> str:
    """
    Generate a comprehensive GitHub-flavored Markdown Evidence Passport.
    """
    pr = result.pull_request
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Scorecard calculation
    verdicts_by_claim = {v.claim_id: v for v in result.verdicts}
    status_counts = {
        "supported": 0,
        "contradicted": 0,
        "partially_supported": 0,
        "insufficient_evidence": 0,
    }
    for v in result.verdicts:
        if v.status in status_counts:
            status_counts[v.status] += 1

    total_claims = len(result.claims)
    badge_color = "brightgreen" if status_counts["contradicted"] == 0 and status_counts["supported"] > 0 else "orange"

    lines = [
        f"# 🛡️ ClaimCheck Evidence Passport",
        f"",
        f"**Repository:** [{pr.owner}/{pr.repo}](https://github.com/{pr.owner}/{pr.repo})  ",
        f"**Pull Request:** [#{pr.number} - {pr.title}]({pr.url})  ",
        f"**Audit Timestamp:** `{now_str}`  ",
        f"**Verification Model:** `{model_name}` (Strict Open-Weight Inference)  ",
        f"**Investigation ID:** `{result.investigation_id}`  ",
        f"",
        f"---",
        f"",
        f"## 📊 Executive Scorecard",
        f"",
        f"- **Total Claims Extracted:** {total_claims}",
        f"- **✅ Supported:** {status_counts['supported']}",
        f"- **⚠️ Partially Supported:** {status_counts['partially_supported']}",
        f"- **❌ Contradicted:** {status_counts['contradicted']}",
        f"- **❓ Insufficient Evidence:** {status_counts['insufficient_evidence']}",
        f"",
        f"---",
        f"",
        f"## 📋 Claims & Verdicts Matrix",
        f"",
        f"| Claim ID | Category | Claim Description | Verdict | Evidence Count |",
        f"| :--- | :--- | :--- | :--- | :--- |",
    ]

    for claim in result.claims:
        v = verdicts_by_claim.get(claim.id)
        status_str = f"**{v.status.upper()}**" if v else "PENDING"
        ev_count = len(v.evidence_ids) if v else 0
        lines.append(f"| `{claim.id}` | {claim.category} | {claim.description} | {status_str} | {ev_count} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 🔍 In-Depth Evidence & Rationale",
        f"",
    ])

    # Index evidence by id
    evidence_by_id = {ev.id: ev for ev in result.evidence}
    tests_by_claim: dict[str, list] = {}
    for t in result.test_scenarios:
        tests_by_claim.setdefault(t.claim_id, []).append(t)

    for claim in result.claims:
        v = verdicts_by_claim.get(claim.id)
        lines.append(f"### Claim `{claim.id}`: {claim.description}")
        lines.append(f"- **Source ({claim.source_type}):** *\"{claim.source_text}\"*")
        if v:
            lines.append(f"- **Status:** `{v.status}`")
            lines.append(f"- **Reasoning:** {v.reasoning}")

            if v.limitations:
                lines.append(f"- **Limitations / Caveats:**")
                for lim in v.limitations:
                    lines.append(f"  - {lim}")

            # Evidence snippets
            if v.evidence_ids:
                lines.append(f"#### Cited Code Evidence:")
                for ev_id in v.evidence_ids:
                    ev = evidence_by_id.get(ev_id)
                    if ev:
                        line_info = f" (Lines {ev.start_line}-{ev.end_line})" if ev.start_line else ""
                        lines.append(f"- **`{ev.file_path}`{line_info}** [{ev.category}]:")
                        lines.append(f"```diff")
                        lines.append(ev.snippet)
                        lines.append(f"```")

        # Test scenarios
        scenarios = tests_by_claim.get(claim.id, [])
        if scenarios:
            lines.append(f"#### Recommended Test Scenarios:")
            for sc in scenarios:
                lines.append(f"- **{sc.description}**  \n  *Expected:* {sc.expected_result}")

        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"*Generated automatically by **ClaimCheck** using approved open-weight model inference.*",
    ])

    return "\n".join(lines)

