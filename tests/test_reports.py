import json
from backend.models import (
    PullRequest,
    Claim,
    Evidence,
    Verdict,
    TestScenario,
    InvestigationResult,
)
from reports.passport import generate_json_passport, generate_markdown_passport


def test_passport_generation():
    pr = PullRequest(
        owner="test-owner",
        repo="test-repo",
        number=7,
        title="Implement secure token rotation",
        description="Rotates refresh tokens every 24 hours.",
        url="https://github.com/test-owner/test-repo/pull/7",
        base_sha="sha1",
        head_sha="sha2",
    )
    claim = Claim(
        id="c-1",
        description="Rotates refresh tokens",
        category="security",
        source_text="Rotates refresh tokens every 24 hours.",
    )
    evidence = Evidence(
        id="ev-1",
        claim_id="c-1",
        file_path="security/tokens.py",
        start_line=15,
        end_line=20,
        snippet="+ if now - token.issued_at > 86400: rotate()",
        category="supporting",
    )
    scenario = TestScenario(
        id="test-1",
        claim_id="c-1",
        description="Verify token expiration triggers rotation",
        expected_result="New token pair generated",
    )
    verdict = Verdict(
        claim_id="c-1",
        status="supported",
        reasoning="Diff includes rotation logic at 86400s threshold.",
        evidence_ids=["ev-1"],
    )

    result = InvestigationResult(
        investigation_id="inv-test-7",
        pull_request=pr,
        claims=[claim],
        evidence=[evidence],
        test_scenarios=[scenario],
        verdicts=[verdict],
    )

    # Test JSON output
    json_str = generate_json_passport(result)
    data = json.loads(json_str)
    assert data["investigation_id"] == "inv-test-7"
    assert data["pull_request"]["number"] == 7

    # Test Markdown output
    md_str = generate_markdown_passport(result, model_name="Qwen 2.5 7B")
    assert "# 🛡️ ClaimCheck Evidence Passport" in md_str
    assert "Qwen 2.5 7B" in md_str
    assert "Rotates refresh tokens" in md_str
    assert "security/tokens.py" in md_str
    assert "SUPPORTED" in md_str

