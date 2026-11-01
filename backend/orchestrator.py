import uuid
import logging
from typing import Any
from ai_engine.interface import AIClientInterface
from ai_engine.mock_client import MockAIClient
from ai_engine.client import get_ai_client
from ai_engine.prompts import extract_claims, verify_claim
from integrations.github_client import (
    GitHubClient,
    GitHubClientError,
    parse_unified_diff,
)
from database.db import save_investigation, DEFAULT_DB_PATH
from backend.models import (
    PullRequest,
    Claim,
    Evidence,
    Verdict,
    TestScenario,
    InvestigationResult,
)

logger = logging.getLogger(__name__)


class InvestigationOrchestrator:
    """
    Coordinates GitHub PR fetching, diff analysis, AI claim extraction,
    evidence verification, verdict synthesis, and database storage.
    """

    def __init__(
        self,
        ai_client: AIClientInterface | None = None,
        github_client: GitHubClient | None = None,
        db_path: str = DEFAULT_DB_PATH,
    ):
        self.ai_client = ai_client or get_ai_client()
        self.github_client = github_client or GitHubClient()
        self.db_path = db_path
        self.using_mock = isinstance(self.ai_client, MockAIClient)

    def run_investigation(
        self,
        pr_url: str,
        sample_diff: str | None = None,
        sample_pr: PullRequest | None = None,
    ) -> InvestigationResult:
        """
        Execute full ClaimCheck verification for a GitHub Pull Request.
        """
        investigation_id = f"inv-{uuid.uuid4().hex[:10]}"

        # 1. Fetch Pull Request details
        if sample_pr:
            pr = sample_pr
        else:
            owner, repo, number = self.github_client.parse_pr_url(pr_url)
            pr = self.github_client.get_pull_request(owner, repo, number)

        # 2. Fetch PR Unified Diff
        if sample_diff is not None:
            diff_text = sample_diff
        else:
            diff_text = self.github_client.get_pull_request_diff(pr.owner, pr.repo, pr.number)

        # 3. Parse diff into evidence candidates
        raw_evidence = parse_unified_diff(diff_text, commit_sha=pr.head_sha)
        candidate_evidence = [
            Evidence(
                id=item["id"],
                claim_id="pending",
                file_path=item["file_path"],
                start_line=item["start_line"],
                end_line=item["end_line"],
                snippet=item["snippet"],
                commit_sha=item["commit_sha"],
                source_url=f"https://github.com/{pr.owner}/{pr.repo}/blob/{pr.head_sha}/{item['file_path']}#L{item['start_line']}",
                category="contextual",
            )
            for item in raw_evidence
        ]

        # 4. Extract atomic claims from PR metadata
        claims = extract_claims(self.ai_client, pr)

        # 5. Verify each claim against candidate evidence
        all_verdicts: list[Verdict] = []
        all_test_scenarios: list[TestScenario] = []
        verified_evidence: list[Evidence] = []
        seen_evidence_ids: set[str] = set()

        for claim in claims:
            verdict, test_scenarios, matched_evidence = verify_claim(
                self.ai_client,
                claim,
                candidate_evidence,
            )
            all_verdicts.append(verdict)
            all_test_scenarios.extend(test_scenarios)

            for ev in matched_evidence:
                if ev.id not in seen_evidence_ids:
                    verified_evidence.append(ev)
                    seen_evidence_ids.add(ev.id)

        # NOTE: Do NOT fall back to dumping all candidate evidence when no claim-specific
        # evidence matched — that would misrepresent unrelated code changes as supporting evidence.
        # The UI and passport will clearly show INSUFFICIENT_EVIDENCE when no match was found.

        # 6. Assemble investigation result, tagging inference mode for transparency
        result = InvestigationResult(
            investigation_id=investigation_id,
            pull_request=pr,
            claims=claims,
            evidence=verified_evidence,
            test_scenarios=all_test_scenarios,
            verdicts=all_verdicts,
            using_mock=self.using_mock,
        )

        # 7. Persist to SQLite
        try:
            save_investigation(result, db_path=self.db_path)
        except Exception as exc:
            logger.error("Failed to save investigation result to SQLite: %s", exc)

        return result

