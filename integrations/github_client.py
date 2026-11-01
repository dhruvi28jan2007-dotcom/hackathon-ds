import os
import re
import requests
from typing import Any
from backend.models import PullRequest, Evidence


class GitHubClientError(Exception):
    """Raised when GitHub API operations fail."""
    pass


class GitHubClient:
    """Client for interacting with GitHub Pull Request APIs."""

    def __init__(self, token: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN") or ""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ClaimCheck-PR-Verifier",
            "Accept": "application/vnd.github.v3+json",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
        """
        Extract (owner, repo, pr_number) from a GitHub PR URL or shorthand notation.
        Supports:
          - https://github.com/owner/repo/pull/123
          - https://github.com/owner/repo/pull/123/files
          - https://github.com/owner/repo/pull/123/commits
          - https://github.com/owner/repo/pull/123?tab=files
          - owner/repo#123
        """
        raw = url.strip()
        if not raw:
            raise GitHubClientError("GitHub PR URL cannot be empty.")

        # Check shorthand format: owner/repo#123
        shorthand_match = re.match(r"^([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)#(\d+)$", raw)
        if shorthand_match:
            owner, repo, number_str = shorthand_match.groups()
            return owner, repo, int(number_str)

        # Ensure domain is github.com
        if "github.com" not in raw.lower():
            raise GitHubClientError(
                f"Invalid GitHub PR URL: '{url}'. Expected domain 'github.com'."
            )

        # Match PR URL with optional trailing paths/parameters
        match = re.search(r"github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)/pull/(\d+)(?:[/?#]|$)", raw)
        if not match:
            raise GitHubClientError(
                f"Invalid GitHub PR URL: '{url}'. Expected format: https://github.com/owner/repo/pull/123"
            )
        owner, repo, number_str = match.groups()
        return owner, repo, int(number_str)

    def _handle_response_errors(self, resp: requests.Response, resource_name: str) -> None:
        """Centralized HTTP response validation for GitHub API calls."""
        if resp.status_code == 401:
            raise GitHubClientError("GitHub API authorization failed (401). Please verify your GITHUB_TOKEN.")

        is_rate_limited = (
            resp.status_code == 403
            and ("rate limit" in resp.text.lower() or resp.headers.get("X-RateLimit-Remaining") == "0")
        )
        if is_rate_limited:
            raise GitHubClientError("GitHub API rate limit exceeded. Please configure a valid GITHUB_TOKEN in .env.")

        if resp.status_code == 404:
            raise GitHubClientError(f"GitHub {resource_name} not found (404). Verify that repository and PR number exist and are public.")

        if resp.status_code != 200:
            raise GitHubClientError(f"GitHub API error ({resp.status_code}) fetching {resource_name}: {resp.text[:200]}")

    def get_pull_request(self, owner: str, repo: str, number: int) -> PullRequest:
        """Fetch PR details and return a backend PullRequest model."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
        try:
            resp = self.session.get(endpoint, timeout=15)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error connecting to GitHub: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number}")

        data = resp.json()
        user_info = data.get("user") or {}
        author = user_info.get("login", "") if isinstance(user_info, dict) else ""
        state = data.get("state", "open") or "open"

        return PullRequest(
            owner=owner,
            repo=repo,
            number=number,
            title=data.get("title", "") or "",
            description=data.get("body") or "",
            url=data.get("html_url", endpoint) or endpoint,
            base_sha=data.get("base", {}).get("sha", "") or "",
            head_sha=data.get("head", {}).get("sha", "") or "",
            author=author,
            state=state,
        )

    def get_pull_request_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch raw unified diff for the Pull Request."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
        headers = dict(self.session.headers)
        headers["Accept"] = "application/vnd.github.v3.diff"

        try:
            resp = self.session.get(endpoint, headers=headers, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching diff: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} diff")
        return resp.text

    def get_pull_request_files(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Fetch changed files list with patches."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/files"
        try:
            resp = self.session.get(endpoint, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching PR files: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} files")
        files_data = resp.json()
        if not isinstance(files_data, list):
            return []
        return files_data

    def get_pull_request_commits(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Fetch commits in the Pull Request."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/commits"
        try:
            resp = self.session.get(endpoint, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching commits: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} commits")
        commits_data = resp.json()
        if not isinstance(commits_data, list):
            return []

        parsed_commits = []
        for c in commits_data:
            commit_info = c.get("commit", {})
            parsed_commits.append({
                "sha": c.get("sha", ""),
                "message": commit_info.get("message", ""),
                "author": commit_info.get("author", {}).get("name", ""),
                "date": commit_info.get("author", {}).get("date", ""),
            })
        return parsed_commits

    def get_pull_request_review_comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Fetch code-level review comments on the PR diff."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/comments"
        try:
            resp = self.session.get(endpoint, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching review comments: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} review comments")
        comments_data = resp.json()
        if not isinstance(comments_data, list):
            return []

        parsed = []
        for item in comments_data:
            parsed.append({
                "id": str(item.get("id", "")),
                "user": item.get("user", {}).get("login", ""),
                "body": item.get("body", ""),
                "path": item.get("path", ""),
                "line": item.get("line") or item.get("original_line"),
                "created_at": item.get("created_at", ""),
            })
        return parsed

    def get_pull_request_issue_comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Fetch general conversation comments from the PR discussion thread."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
        try:
            resp = self.session.get(endpoint, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching issue comments: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} discussion comments")
        comments_data = resp.json()
        if not isinstance(comments_data, list):
            return []

        parsed = []
        for item in comments_data:
            parsed.append({
                "id": str(item.get("id", "")),
                "user": item.get("user", {}).get("login", ""),
                "body": item.get("body", ""),
                "created_at": item.get("created_at", ""),
            })
        return parsed

    def get_pull_request_reviews(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Fetch submitted reviews and their states (APPROVED, CHANGES_REQUESTED, COMMENTED)."""
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews"
        try:
            resp = self.session.get(endpoint, timeout=20)
        except requests.RequestException as exc:
            raise GitHubClientError(f"Network error fetching reviews: {str(exc)}") from exc

        self._handle_response_errors(resp, f"PR #{number} reviews")
        reviews_data = resp.json()
        if not isinstance(reviews_data, list):
            return []

        parsed = []
        for r in reviews_data:
            parsed.append({
                "id": str(r.get("id", "")),
                "user": r.get("user", {}).get("login", ""),
                "state": r.get("state", ""),
                "body": r.get("body", "") or "",
                "submitted_at": r.get("submitted_at", ""),
            })
        return parsed


def parse_unified_diff(diff_text: str, commit_sha: str = "") -> list[dict[str, Any]]:
    """
    Parse a unified git diff into file patches with line ranges, snippet content,
    and change categories (including added, modified, and deleted files).
    """
    if not diff_text or not diff_text.strip():
        return []

    evidence_items = []
    file_chunks = re.split(r"^diff --git ", diff_text, flags=re.MULTILINE)

    evidence_counter = 1
    for chunk in file_chunks:
        if not chunk.strip():
            continue

        # Extract target file name (handles normal additions/modifications and deleted files)
        file_path = ""
        file_match = re.search(r"^\+\+\+ b/(.*)$", chunk, re.MULTILINE)
        if file_match and file_match.group(1).strip() != "/dev/null":
            file_path = file_match.group(1).strip()
        else:
            # Check for deleted file (--- a/<path> +++ /dev/null)
            deleted_match = re.search(r"^--- a/(.*)$", chunk, re.MULTILINE)
            if deleted_match:
                file_path = deleted_match.group(1).strip()

        if not file_path:
            continue

        # Extract hunks
        hunk_pattern = re.compile(
            r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@([^\n]*)\n([\s\S]*?)(?=(?:^@@|\Z))",
            re.MULTILINE,
        )

        hunk_matches = list(hunk_pattern.finditer(chunk))
        if not hunk_matches:
            # File deletion or rename without hunks
            evidence_items.append({
                "id": f"ev-{evidence_counter}",
                "file_path": file_path,
                "start_line": 1,
                "end_line": 1,
                "snippet": chunk[:500],
                "commit_sha": commit_sha,
            })
            evidence_counter += 1
            continue

        for match in hunk_matches:
            orig_start, orig_len, new_start, new_len, _header, hunk_body = match.groups()
            start_line = int(new_start) if new_start and int(new_start) > 0 else (int(orig_start) if orig_start else 1)
            line_count = int(new_len) if new_len else (int(orig_len) if orig_len else 1)
            end_line = start_line + max(line_count - 1, 0)

            # Keep snippet concise (up to 30 lines)
            snippet_lines = hunk_body.splitlines()[:30]
            snippet = "\n".join(snippet_lines)

            evidence_items.append({
                "id": f"ev-{evidence_counter}",
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "snippet": snippet,
                "commit_sha": commit_sha,
            })
            evidence_counter += 1

    return evidence_items
