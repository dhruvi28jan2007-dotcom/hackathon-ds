from backend.models import Claim, Verdict


def test_claim_creation():
    claim = Claim(
        id="claim-1",
        description="The API validates input",
        source_text="We added input validation.",
    )

    assert claim.id == "claim-1"
    assert claim.category == "general"


def test_verdict_creation():
    verdict = Verdict(
        claim_id="claim-1",
        status="supported",
        reasoning="Evidence supports the claim.",
    )

    assert verdict.status == "supported"
    assert verdict.evidence_ids == []