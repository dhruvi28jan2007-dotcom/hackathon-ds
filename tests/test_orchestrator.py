import os
import tempfile
from ai_engine.mock_client import MockAIClient
from backend.models import PullRequest
from backend.orchestrator import InvestigationOrchestrator
from database.db import get_investigation

SAMPLE_DIFF = """diff --git a/services/auth.py b/services/auth.py
index 1111111..2222222 100644
--- a/services/auth.py
+++ b/services/auth.py
@@ -25,4 +25,8 @@ def authenticate(user, token):
+    if not token or token.expired():
+        raise AuthError("Invalid or expired session")
     return True
"""


def test_investigation_orchestrator_pipeline():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        mock_ai = MockAIClient()
        orchestrator = InvestigationOrchestrator(
            ai_client=mock_ai,
            db_path=db_path,
        )

        sample_pr = PullRequest(
            owner="axiom-team",
            repo="claimcheck-core",
            number=101,
            title="Enforce session expiration checks",
            description="We validate token expiration before allowing access.",
            url="https://github.com/axiom-team/claimcheck-core/pull/101",
            base_sha="base_hash",
            head_sha="head_hash",
        )

        result = orchestrator.run_investigation(
            pr_url="https://github.com/axiom-team/claimcheck-core/pull/101",
            sample_diff=SAMPLE_DIFF,
            sample_pr=sample_pr,
        )

        assert result.investigation_id.startswith("inv-")
        assert len(result.claims) > 0
        assert len(result.verdicts) > 0
        assert len(result.evidence) > 0
        assert result.verdicts[0].status in (
            "supported",
            "contradicted",
            "partially_supported",
            "insufficient_evidence",
        )

        # Check DB persistence
        db_result = get_investigation(result.investigation_id, db_path=db_path)
        assert db_result is not None
        assert db_result.pull_request.title == sample_pr.title
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

