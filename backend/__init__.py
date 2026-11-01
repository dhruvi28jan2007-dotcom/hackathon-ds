from backend.models import (
    VerdictStatus,
    PullRequest,
    Claim,
    Evidence,
    TestScenario,
    Verdict,
    InvestigationResult,
)
__all__ = [
    "VerdictStatus",
    "PullRequest",
    "Claim",
    "Evidence",
    "TestScenario",
    "Verdict",
    "InvestigationResult",
    "InvestigationOrchestrator",
]


def __getattr__(name: str):
    if name == "InvestigationOrchestrator":
        from backend.orchestrator import InvestigationOrchestrator
        return InvestigationOrchestrator
    raise AttributeError(f"module 'backend' has no attribute '{name}'")

