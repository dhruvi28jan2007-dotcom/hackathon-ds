import json
import re
from typing import Any
from ai_engine.interface import AIClientInterface


class MockAIClient(AIClientInterface):
    """
    Deterministic mock AI client for testing and offline execution.

    IMPORTANT: The mock client generates responses based on the actual PR content
    present in the prompt. It NEVER returns hardcoded domain-specific claims
    (authentication, database reconnection) for arbitrary PRs.
    """

    def __init__(self, canned_responses: dict[str, Any] | None = None):
        self.canned_responses = canned_responses or {}
        self.last_prompt = ""
        self.last_system_prompt = ""
        self.call_count = 0

    def check_health(self) -> tuple[bool, str]:
        return True, "Mock AI Client is active (offline/test mode)"

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt or ""
        self.call_count += 1

        # 1. Check canned responses keyed by the caller
        for key, response in self.canned_responses.items():
            if key in prompt or (system_prompt and key in system_prompt):
                if isinstance(response, (dict, list)):
                    return json.dumps(response)
                return str(response)

        lower_prompt = prompt.lower()

        # 2. Claim extraction: derive claims from the actual PR title/description
        #    present in the prompt, NOT from hardcoded fiction.
        if (
            "extract all verifiable technical claims" in lower_prompt
            or "extract claims" in lower_prompt
            or (system_prompt and "extract" in (system_prompt or "").lower() and "claims" in lower_prompt)
        ):
            return self._generate_claims_from_prompt(prompt)

        # 3. Claim verification: assess evidence IDs present in the prompt
        if "claim to verify" in lower_prompt or "evidence candidates" in lower_prompt:
            return self._generate_verdict_from_prompt(prompt)

        # 4. Fallback
        return json.dumps({"status": "ok", "message": "Mock completion response"})

    def _generate_claims_from_prompt(self, prompt: str) -> str:
        """
        Extract the PR title and description from the prompt text and generate
        mock claims that actually reflect the PR content.
        """
        # Parse PR number and title
        title = ""
        description = ""

        title_match = re.search(r"Pull Request #\d+:\s*(.+)", prompt)
        if title_match:
            title = title_match.group(1).strip()

        desc_match = re.search(r"Description:\s*([\s\S]+?)(?:\n\nExtract|\Z)", prompt)
        if desc_match:
            description = desc_match.group(1).strip()

        # Parse numbered list items from the description as individual claims
        lines = (description or title).splitlines()
        numbered = [
            re.sub(r"^\s*\d+[\.\)]\s*", "", line).strip()
            for line in lines
            if re.match(r"^\s*\d+[\.\)]\s+", line) and len(line.strip()) > 5
        ]

        if not numbered:
            # Fall back to the PR title as a single claim
            text = title or "(No description provided)"
            return json.dumps([{
                "id": "claim-1",
                "description": text,
                "category": "general",
                "source_text": text,
                "source_type": "title",
            }])

        claims = []
        for idx, item in enumerate(numbered[:5], start=1):
            claims.append({
                "id": f"claim-{idx}",
                "description": item,
                "category": "general",
                "source_text": item,
                "source_type": "description",
            })
        return json.dumps(claims)

    def _generate_verdict_from_prompt(self, prompt: str) -> str:
        """
        Generate a verdict based on whether the evidence blocks in the prompt
        contain keywords from the claim description. Returns INSUFFICIENT_EVIDENCE
        when no relevant evidence is found.
        """
        # Extract claim description
        claim_desc = ""
        claim_match = re.search(r"Claim:\s*(.+?)(?:\nSource:|\Z)", prompt, re.DOTALL)
        if claim_match:
            claim_desc = claim_match.group(1).strip()

        # Extract evidence block
        evidence_text = ""
        ev_match = re.search(r"CODE CHANGES / EVIDENCE CANDIDATES:\s*([\s\S]+)", prompt)
        if ev_match:
            evidence_text = ev_match.group(1).strip()

        # Determine evidence IDs present
        ev_ids = re.findall(r"\[(ev-\d+)\]", prompt)

        # No evidence available
        if not evidence_text or evidence_text.startswith("(No code changes"):
            return json.dumps({
                "status": "insufficient_evidence",
                "reasoning": (
                    f"No code diff evidence is available to verify the claim: '{claim_desc}'. "
                    "Cannot confirm implementation without seeing code changes."
                ),
                "evidence_ids": [],
                "limitations": [
                    "No diff or changed files were retrieved for this PR.",
                    "Manual review of the actual code changes is required.",
                ],
                "test_scenarios": [],
            })

        # Keyword-match claim words against evidence content
        stop_words = {
            "this", "that", "with", "from", "have", "were", "which", "when",
            "what", "then", "they", "will", "your", "also", "upon", "been",
            "their", "more", "into", "than", "some", "each",
        }
        claim_words = [
            w.lower() for w in re.findall(r"[a-zA-Z]{4,}", claim_desc)
            if w.lower() not in stop_words
        ]

        matched_ev_ids = []
        for ev_id in ev_ids:
            # Find this evidence block's content in the prompt
            block_pattern = re.escape(ev_id) + r"\].*?(?=\[ev-|\Z)"
            block_match = re.search(block_pattern, prompt, re.DOTALL)
            block_text = block_match.group(0).lower() if block_match else ""
            if any(word in block_text for word in claim_words):
                matched_ev_ids.append(ev_id)

        if matched_ev_ids:
            return json.dumps({
                "status": "supported",
                "reasoning": (
                    f"The diff contains changes in evidence items {matched_ev_ids} "
                    f"that are relevant to: '{claim_desc}'."
                ),
                "evidence_ids": matched_ev_ids,
                "limitations": [
                    "Mock verification: confirm with real open-weight model for authoritative result.",
                ],
                "test_scenarios": [],
            })
        else:
            return json.dumps({
                "status": "insufficient_evidence",
                "reasoning": (
                    f"None of the {len(ev_ids)} evidence block(s) in the diff contain terms "
                    f"matching the claim: '{claim_desc}'. "
                    "The changed files do not appear to implement this specific claim."
                ),
                "evidence_ids": [],
                "limitations": [
                    "Keyword matching only — real open-weight model inference recommended.",
                    f"Claim terms searched: {claim_words}",
                ],
                "test_scenarios": [],
            })
