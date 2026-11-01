import os
import tempfile
from backend.models import PullRequest, Claim, Verdict, InvestigationResult
from database.db import init_db, save_investigation, get_investigation, list_investigations


def test_sqlite_investigation_lifecycle():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        init_db(db_path)
        pr = PullRequest(
            owner="demo-org",
            repo="demo-repo",
            number=42,
            title="Fix SQL injection",
            description="Sanitizes user input",
            url="https://github.com/demo-org/demo-repo/pull/42",
            base_sha="base_abc",
            head_sha="head_def",
        )
        claim = Claim(id="c-1", description="Sanitizes SQL", category="security")
        verdict = Verdict(claim_id="c-1", status="supported", reasoning="Parameterized queries used")
        res = InvestigationResult(
            investigation_id="inv-123",
            pull_request=pr,
            claims=[claim],
            verdicts=[verdict],
        )

        save_investigation(res, db_path=db_path)

        retrieved = get_investigation("inv-123", db_path=db_path)
        assert retrieved is not None
        assert retrieved.investigation_id == "inv-123"
        assert retrieved.pull_request.repo == "demo-repo"
        assert len(retrieved.claims) == 1
        assert retrieved.verdicts[0].status == "supported"

        inv_list = list_investigations(db_path=db_path)
        assert len(inv_list) == 1
        assert inv_list[0]["pr_number"] == 42
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

