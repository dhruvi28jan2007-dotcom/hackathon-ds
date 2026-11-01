import json
import logging
from typing import Any
from ai_engine.interface import AIClientInterface
from backend.models import (
    PullRequest,
    Claim,
    Evidence,
    Verdict,
    VerdictStatus,
    TestScenario,
)

logger = logging.getLogger(__name__)

CLAIM_EXTRACTION_SYSTEM_PROMPT = """You are ClaimCheck, an automated GitHub PR audit engine.
Your task is to analyze a Pull Request's title and description to extract all verifiable claims, assertions, or promises made by the author.

CRITICAL INSTRUCTIONS:
1. Extract distinct, atomic technical claims (e.g. bug fixes, feature additions, validation rules, security guarantees, performance improvements).
2. Return ONLY a valid JSON array of objects.
3. Each object must have:
   - "id": string (e.g. "claim-1", "claim-2")
   - "description": clear, testable assertion of what the PR claims to do
   - "category": one of "bugfix", "feature", "security", "performance", "refactor", "general"
   - "source_text": exact or paraphrased sentence from the title or description
   - "source_type": "title" or "description"
"""

CLAIM_EXTRACTION_USER_PROMPT = """Pull Request #{number}: {title}

Description:
{description}

Extract all verifiable technical claims as a JSON array."""


VERIFICATION_SYSTEM_PROMPT = """You are ClaimCheck, a precise code reviewer and evidence verification engine.
Your task is to evaluate a single technical claim against the code changes (git diff snippets) provided.

Determine whether the code changes actually support, contradict, partially support, or provide insufficient evidence for the claim.

VERDICT CRITERIA:
- "supported": The code changes directly implement or satisfy the claim.
- "contradicted": The code changes do the opposite, break the expectation, or fail to fulfill the claim.
- "partially_supported": Some parts of the claim are implemented, but significant parts are omitted.
- "insufficient_evidence": The diff snippets do not contain enough information or files changed to verify the claim.

Return ONLY a valid JSON object with:
- "status": one of "supported", "contradicted", "partially_supported", "insufficient_evidence"
- "reasoning": concise technical analysis citing the code changes
- "evidence_ids": array of evidence IDs (e.g. ["ev-1", "ev-2"]) that were relevant
- "limitations": list of limitations or things not verifiable from this diff alone
- "test_scenarios": list of objects with "id", "description", and "expected_result" to test this claim
"""

VERIFICATION_USER_PROMPT = """CLAIM TO VERIFY:
ID: {claim_id}
Category: {claim_category}
Claim: {claim_description}
Source: "{source_text}"

CODE CHANGES / EVIDENCE CANDIDATES:
{evidence_text}

Evaluate this claim against the provided evidence and return your verdict JSON object."""


def extract_claims(client: AIClientInterface, pr: PullRequest) -> list[Claim]:
    """
    Extract atomic technical claims from a PR's title and body using the AI client.
    """
    user_prompt = CLAIM_EXTRACTION_USER_PROMPT.format(
        number=pr.number,
        title=pr.title,
        description=pr.description or "(No description provided)",
    )

    try:
        raw_claims = client.generate_json(
            prompt=user_prompt,
            system_prompt=CLAIM_EXTRACTION_SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.warning("AI claim extraction failed, falling back to rule-based claim extraction: %s", exc)
        raw_claims = []

    # If AI extracted empty or invalid list, fallback to rule-based claim from PR title
    if not isinstance(raw_claims, list) or len(raw_claims) == 0:
        raw_claims = [{
            "id": "claim-1",
            "description": pr.title.strip() or "General pull request changes",
            "category": "general",
            "source_text": pr.title.strip(),
            "source_type": "title",
        }]

    claims: list[Claim] = []
    for idx, item in enumerate(raw_claims, start=1):
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("id") or f"claim-{idx}")
        claims.append(
            Claim(
                id=claim_id,
                description=str(item.get("description") or f"PR Assertion #{idx}"),
                category=str(item.get("category") or "general"),
                source_text=str(item.get("source_text") or pr.title),
                source_type=str(item.get("source_type") or "description"),
            )
        )
    return claims


def verify_claim(
    client: AIClientInterface,
    claim: Claim,
    evidence_list: list[Evidence],
) -> tuple[Verdict, list[TestScenario], list[Evidence]]:
    """
    Verify a claim against candidate code evidence and produce a Verdict and TestScenarios.
    """
    # Format candidate evidence text
    if not evidence_list:
        evidence_text = "(No code changes or diff evidence available for this PR)"
    else:
        pieces = []
        for ev in evidence_list[:10]:  # Limit to 10 snippets to fit context window comfortably
            lines = f"Lines {ev.start_line}-{ev.end_line}" if ev.start_line else "Hunk"
            pieces.append(f"[{ev.id}] File: {ev.file_path} ({lines})\n```\n{ev.snippet}\n```")
        evidence_text = "\n\n".join(pieces)

    user_prompt = VERIFICATION_USER_PROMPT.format(
        claim_id=claim.id,
        claim_category=claim.category,
        claim_description=claim.description,
        source_text=claim.source_text,
        evidence_text=evidence_text,
    )

    try:
        data = client.generate_json(
            prompt=user_prompt,
            system_prompt=VERIFICATION_SYSTEM_PROMPT,
        )
    except Exception as exc:
        logger.warning("AI claim verification failed: %s", exc)
        data = {}

    if not isinstance(data, dict):
        data = {}

    valid_statuses: set[VerdictStatus] = {
        "supported",
        "contradicted",
        "partially_supported",
        "insufficient_evidence",
    }

    status = data.get("status")
    if status not in valid_statuses:
        # Default to insufficient_evidence when AI returns an invalid/missing status.
        # Having evidence in the diff does NOT automatically mean it supports the claim.
        status: VerdictStatus = "insufficient_evidence"

    reasoning = str(data.get("reasoning") or (
        f"No conclusive evidence found in diff for claim: '{claim.description}'."
    ))

    used_ev_ids = data.get("evidence_ids")
    if not isinstance(used_ev_ids, list):
        # Do NOT auto-assign evidence when AI provides no IDs — evidence must be
        # explicitly cited by the model to count as supporting a claim.
        used_ev_ids = []

    limitations = data.get("limitations")
    if not isinstance(limitations, list):
        limitations = []

    verdict = Verdict(
        claim_id=claim.id,
        status=status,
        reasoning=reasoning,
        evidence_ids=[str(i) for i in used_ev_ids],
        limitations=[str(l) for l in limitations],
    )

    # Tag evidence items with this claim_id and category — only those explicitly cited
    claim_evidences: list[Evidence] = []
    for ev in evidence_list:
        if ev.id in used_ev_ids:
            cat = "supporting" if status in ("supported", "partially_supported") else (
                "contradicting" if status == "contradicted" else "contextual"
            )
            claim_evidences.append(
                Evidence(
                    id=ev.id,
                    claim_id=claim.id,
                    file_path=ev.file_path,
                    start_line=ev.start_line,
                    end_line=ev.end_line,
                    snippet=ev.snippet,
                    commit_sha=ev.commit_sha,
                    source_url=ev.source_url,
                    category=cat,
                )
            )

    # Parse test scenarios
    raw_scenarios = data.get("test_scenarios")
    test_scenarios: list[TestScenario] = []
    if isinstance(raw_scenarios, list):
        for idx, sc in enumerate(raw_scenarios, start=1):
            if isinstance(sc, dict):
                test_scenarios.append(
                    TestScenario(
                        id=str(sc.get("id") or f"test-{claim.id}-{idx}"),
                        claim_id=claim.id,
                        description=str(sc.get("description") or "Validate claim behavior in unit tests"),
                        expected_result=str(sc.get("expected_result") or "Assertion passes as expected"),
                        execution_status="proposed",
                    )
                )

    if not test_scenarios:
        test_scenarios.append(
            TestScenario(
                id=f"test-{claim.id}-1",
                claim_id=claim.id,
                description=f"Automated unit test verifying: {claim.description}",
                expected_result="Passes with expected return value and side effects",
                execution_status="proposed",
            )
        )

    return verdict, test_scenarios, claim_evidences

