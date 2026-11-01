from typing import Literal
from pydantic import BaseModel, Field


VerdictStatus = Literal[
    "supported",
    "contradicted",
    "partially_supported",
    "insufficient_evidence",
]


class PullRequest(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    description: str = ""
    url: str
    base_sha: str
    head_sha: str
    author: str = ""
    state: str = "open"


class Claim(BaseModel):
    id: str
    description: str
    category: str = "general"
    source_text: str = ""
    source_type: str = "description"


class Evidence(BaseModel):
    id: str
    claim_id: str
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    snippet: str
    commit_sha: str = ""
    source_url: str = ""
    category: Literal[
        "supporting",
        "contradicting",
        "contextual",
    ] = "contextual"


class TestScenario(BaseModel):
    __test__ = False
    id: str
    claim_id: str
    description: str
    expected_result: str
    execution_status: Literal[
        "proposed",
        "executed",
        "passed",
        "failed",
    ] = "proposed"


class Verdict(BaseModel):
    claim_id: str
    status: VerdictStatus
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    investigation_id: str
    pull_request: PullRequest
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    test_scenarios: list[TestScenario] = Field(default_factory=list)
    verdicts: list[Verdict] = Field(default_factory=list)
    using_mock: bool = True  # True when MockAIClient was used; False for real open-weight model