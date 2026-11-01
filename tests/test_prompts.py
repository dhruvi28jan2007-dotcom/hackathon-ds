from ai_engine.mock_client import MockAIClient
from ai_engine.prompts import extract_claims, verify_claim
from backend.models import PullRequest, Evidence


def test_extract_claims_with_mock():
    client = MockAIClient()
    pr = PullRequest(
        owner="owner",
        repo="repo",
        number=1,
        title="Add auth validation and db reconnect",
        description="We added authentication validation and auto-reconnects to database.",
        url="https://github.com/owner/repo/pull/1",
        base_sha="base",
        head_sha="head",
    )

    claims = extract_claims(client, pr)
    assert len(claims) >= 1
    assert claims[0].id == "claim-1"
    assert claims[0].description != ""


def test_verify_claim_with_mock():
    client = MockAIClient()
    pr = PullRequest(
        owner="owner",
        repo="repo",
        number=1,
        title="Add auth validation",
        description="Validation",
        url="https://github.com/owner/repo/pull/1",
        base_sha="base",
        head_sha="head",
    )
    claims = extract_claims(client, pr)
    claim = claims[0]

    sample_ev = [
        Evidence(
            id="ev-1",
            claim_id="claim-1",
            file_path="auth.py",
            start_line=1,
            end_line=5,
            snippet="+ if not token.is_valid(): raise AuthError()",
        )
    ]

    verdict, test_scenarios, matched_ev = verify_claim(client, claim, sample_ev)
    assert verdict.claim_id == claim.id
    assert verdict.status in ("supported", "contradicted", "partially_supported", "insufficient_evidence")
    assert len(test_scenarios) > 0
    assert len(matched_ev) > 0


# ---------------------------------------------------------------------------
# Regression tests: vscode#345386 "Fix pet propeller accessory rendering"
# These guard against MockAIClient fabricating unrelated auth/database claims.
# ---------------------------------------------------------------------------

def _propeller_pr() -> PullRequest:
    return PullRequest(
        owner="microsoft",
        repo="vscode",
        number=345386,
        title="Fix pet propeller accessory rendering",
        description=(
            "This PR fixes the pivot animation for the pet propeller accessory.\n"
            "The rendering pipeline was skipping the rotation matrix update,\n"
            "causing incorrect accessory orientation on high-DPI displays.\n"
        ),
        url="https://github.com/microsoft/vscode/pull/345386",
        base_sha="aabbcc",
        head_sha="ddeeff",
    )


def test_propeller_pr_claims_are_not_hardcoded_auth():
    """MockAIClient must NOT return authentication or database claims for a rendering PR."""
    client = MockAIClient()
    claims = extract_claims(client, _propeller_pr())

    assert len(claims) >= 1
    lowered = " ".join(c.description.lower() for c in claims)
    # Claims must NOT contain terms from the old hardcoded fiction
    assert "authentication" not in lowered, f"Fabricated auth claim: {lowered}"
    assert "database" not in lowered, f"Fabricated database claim: {lowered}"
    assert "token expiration" not in lowered, f"Fabricated token claim: {lowered}"
    # Claims should be related to the actual PR
    assert any(
        word in lowered
        for word in ("propeller", "rendering", "pet", "animation", "pivot", "accessory", "fix", "rotation")
    ), f"Claims don't reflect the actual PR: {lowered}"


def test_propeller_pr_insufficient_evidence_with_unrelated_diff():
    """A rendering PR claim must get INSUFFICIENT_EVIDENCE when diff has no rendering code."""
    client = MockAIClient()
    claims = extract_claims(client, _propeller_pr())
    claim = claims[0]

    # Diff that is clearly unrelated to rendering / propellers
    unrelated_evidence = [
        Evidence(
            id="ev-1",
            claim_id=claim.id,
            file_path="src/vs/workbench/services/auth/tokenManager.ts",
            start_line=10,
            end_line=15,
            snippet="+ if (!token.isValid()) { throw new AuthError('Token expired'); }",
        ),
        Evidence(
            id="ev-2",
            claim_id=claim.id,
            file_path="src/vs/platform/database/reconnect.ts",
            start_line=5,
            end_line=10,
            snippet="+ await db.reconnect({ maxRetries: 3 });",
        ),
    ]

    verdict, _, _ = verify_claim(client, claim, unrelated_evidence)
    assert verdict.status == "insufficient_evidence", (
        f"Expected INSUFFICIENT_EVIDENCE for unrelated diff, got: {verdict.status}\n"
        f"Reasoning: {verdict.reasoning}"
    )


def test_two_claims_do_not_share_reasoning():
    """Each claim must get its own unique reasoning from the mock, not copy-pasted text."""
    client = MockAIClient()
    pr = PullRequest(
        owner="test",
        repo="repo",
        number=99,
        title="Fix propeller rendering and update pivot matrix",
        description=(
            "1. Fix propeller rotation for pet accessories.\n"
            "2. Update pivot matrix calculations for high-DPI screens.\n"
        ),
        url="https://github.com/test/repo/pull/99",
        base_sha="aaa",
        head_sha="bbb",
    )
    claims = extract_claims(client, pr)
    # Should have extracted at least 2 claims from the numbered list
    assert len(claims) >= 2, f"Expected >= 2 claims, got {len(claims)}: {[c.description for c in claims]}"

    # Verify both claims; give each distinct evidence
    ev_for_claim1 = [
        Evidence(
            id="ev-1",
            claim_id=claims[0].id,
            file_path="propeller.ts",
            start_line=1,
            end_line=5,
            snippet="+ propeller.rotation = fixedAngle;",
        )
    ]
    ev_for_claim2 = [
        Evidence(
            id="ev-2",
            claim_id=claims[1].id,
            file_path="pivotMatrix.ts",
            start_line=10,
            end_line=15,
            snippet="+ pivot.updateMatrix(dpiScale);",
        )
    ]

    verdict1, _, _ = verify_claim(client, claims[0], ev_for_claim1)
    verdict2, _, _ = verify_claim(client, claims[1], ev_for_claim2)

    # Reasoning must be different between two different claims
    assert verdict1.reasoning != verdict2.reasoning, (
        "Both claims returned identical reasoning — evidence not properly isolated per claim.\n"
        f"Verdict 1 ({claims[0].description}): {verdict1.reasoning}\n"
        f"Verdict 2 ({claims[1].description}): {verdict2.reasoning}"
    )


def test_fallback_status_is_insufficient_evidence_not_supported():
    """
    Regression: verify_claim must NOT default to 'supported' when AI returns invalid status
    and evidence is present. Having evidence in the diff is not the same as the evidence
    supporting the claim.
    """
    # Use a canned response that returns an invalid status to trigger the fallback path
    client = MockAIClient(canned_responses={
        "CLAIM TO VERIFY": {
            "status": "INVALID_STATUS",
            "reasoning": "bad response",
            "evidence_ids": [],
            "limitations": [],
        }
    })
    from backend.models import Claim
    claim = Claim(
        id="claim-1",
        description="Adds token refresh logic",
        category="security",
        source_text="Adds token refresh",
        source_type="title",
    )
    evidence = [
        Evidence(
            id="ev-1",
            claim_id="claim-1",
            file_path="auth.py",
            start_line=1,
            end_line=3,
            snippet="+ token.refresh()",
        )
    ]
    verdict, _, _ = verify_claim(client, claim, evidence)
    assert verdict.status == "insufficient_evidence", (
        f"Fallback with invalid AI status and evidence present should be "
        f"'insufficient_evidence', got '{verdict.status}'"
    )
