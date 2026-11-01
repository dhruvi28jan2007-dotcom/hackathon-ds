import pytest
import requests
from unittest.mock import MagicMock, patch
from integrations.github_client import (
    GitHubClient,
    GitHubClientError,
    parse_unified_diff,
)


# ---------------------------------------------------------------------------
# Test 1 & 2: Valid and Invalid GitHub PR URL Formats
# ---------------------------------------------------------------------------

def test_parse_pr_url_valid_formats():
    """Verify standard URLs, subpaths, query parameters, and shorthand notation."""
    urls = [
        ("https://github.com/octocat/Hello-World/pull/42", ("octocat", "Hello-World", 42)),
        ("https://github.com/octocat/Hello-World/pull/42/files", ("octocat", "Hello-World", 42)),
        ("https://github.com/octocat/Hello-World/pull/42/commits", ("octocat", "Hello-World", 42)),
        ("https://github.com/octocat/Hello-World/pull/42?tab=files", ("octocat", "Hello-World", 42)),
        ("octocat/Hello-World#42", ("octocat", "Hello-World", 42)),
    ]
    for url_input, expected in urls:
        assert GitHubClient.parse_pr_url(url_input) == expected


def test_parse_pr_url_invalid_formats():
    """Verify rejection of empty strings, non-GitHub domains, issues, and non-numeric PRs."""
    invalid_urls = [
        "",
        "   ",
        "https://gitlab.com/octocat/Hello-World/pull/42",
        "https://github.com/octocat/Hello-World/issues/42",
        "https://github.com/octocat/Hello-World/pull/abc",
        "just-a-random-string",
    ]
    for bad_url in invalid_urls:
        with pytest.raises(GitHubClientError):
            GitHubClient.parse_pr_url(bad_url)


# ---------------------------------------------------------------------------
# Test 3: Non-existent PR (HTTP 404)
# ---------------------------------------------------------------------------

def test_get_pull_request_not_found():
    """Verify 404 is cleanly converted into GitHubClientError."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"message": "Not Found"}'

    with patch.object(client.session, "get", return_value=mock_resp):
        with pytest.raises(GitHubClientError) as exc_info:
            client.get_pull_request("owner", "repo", 999999)
        assert "not found (404)" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 4: Fetch PR Title, Description and Metadata
# ---------------------------------------------------------------------------

def test_get_pull_request_metadata():
    """Verify metadata extraction into PullRequest model."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "title": "Fix memory leak in pool",
        "body": "This PR cleans up idle connections.",
        "html_url": "https://github.com/owner/repo/pull/15",
        "base": {"sha": "base_sha_123"},
        "head": {"sha": "head_sha_456"},
        "user": {"login": "octocat"},
        "state": "open",
    }

    with patch.object(client.session, "get", return_value=mock_resp):
        pr = client.get_pull_request("owner", "repo", 15)
        assert pr.title == "Fix memory leak in pool"
        assert pr.description == "This PR cleans up idle connections."
        assert pr.base_sha == "base_sha_123"
        assert pr.head_sha == "head_sha_456"
        assert pr.number == 15
        assert pr.author == "octocat"
        assert pr.state == "open"


# ---------------------------------------------------------------------------
# Test 5: Fetch Changed Files and Handle Missing Patches (e.g. Binary Files)
# ---------------------------------------------------------------------------

def test_get_pull_request_files_with_binary_and_missing_patches():
    """Verify changed files list handles files with null patches without crashing."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"filename": "app.py", "status": "modified", "patch": "@@ -1 +1 @@\n-old\n+new"},
        {"filename": "logo.png", "status": "added", "patch": None},  # Binary file
        {"filename": "huge.json", "status": "modified"},  # Missing patch key
    ]

    with patch.object(client.session, "get", return_value=mock_resp):
        files = client.get_pull_request_files("owner", "repo", 15)
        assert len(files) == 3
        assert files[0]["filename"] == "app.py"
        assert files[1]["patch"] is None


# ---------------------------------------------------------------------------
# Test 6: Fetch Commits
# ---------------------------------------------------------------------------

def test_get_pull_request_commits():
    """Verify commit history extraction."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "sha": "c1a2b3c",
            "commit": {
                "message": "Add connection pool cleanup",
                "author": {"name": "Developer One", "date": "2026-10-31T10:00:00Z"},
            },
        },
        {
            "sha": "d4e5f6g",
            "commit": {
                "message": "Add unit test for idle timer",
                "author": {"name": "Developer One", "date": "2026-10-31T11:00:00Z"},
            },
        },
    ]

    with patch.object(client.session, "get", return_value=mock_resp):
        commits = client.get_pull_request_commits("owner", "repo", 15)
        assert len(commits) == 2
        assert commits[0]["sha"] == "c1a2b3c"
        assert commits[0]["message"] == "Add connection pool cleanup"
        assert commits[0]["author"] == "Developer One"


# ---------------------------------------------------------------------------
# Test 7: Fetch Review Comments and Issue Comments Separately
# ---------------------------------------------------------------------------

def test_get_review_and_issue_comments_separated():
    """Verify separate fetching of code-level review comments vs discussion comments."""
    client = GitHubClient()

    # Code-level review comments
    mock_review_resp = MagicMock()
    mock_review_resp.status_code = 200
    mock_review_resp.json.return_value = [
        {
            "id": 101,
            "user": {"login": "senior_reviewer"},
            "body": "Did you verify this handles disconnect timeouts?",
            "path": "pool.py",
            "line": 42,
            "created_at": "2026-10-31T12:00:00Z",
        }
    ]

    # Discussion thread comments
    mock_issue_resp = MagicMock()
    mock_issue_resp.status_code = 200
    mock_issue_resp.json.return_value = [
        {
            "id": 201,
            "user": {"login": "author_user"},
            "body": "Yes, tested locally with simulated disconnects.",
            "created_at": "2026-10-31T12:30:00Z",
        }
    ]

    with patch.object(client.session, "get", side_effect=[mock_review_resp, mock_issue_resp]):
        review_comments = client.get_pull_request_review_comments("owner", "repo", 15)
        issue_comments = client.get_pull_request_issue_comments("owner", "repo", 15)

        assert len(review_comments) == 1
        assert review_comments[0]["path"] == "pool.py"
        assert review_comments[0]["line"] == 42
        assert review_comments[0]["user"] == "senior_reviewer"

        assert len(issue_comments) == 1
        assert issue_comments[0]["user"] == "author_user"
        assert "tested locally" in issue_comments[0]["body"]


# ---------------------------------------------------------------------------
# Test 8: Fetch Submitted Reviews and Their States
# ---------------------------------------------------------------------------

def test_get_pull_request_reviews():
    """Verify retrieval of submitted review states (APPROVED, CHANGES_REQUESTED)."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "id": 501,
            "user": {"login": "sec_auditor"},
            "state": "APPROVED",
            "body": "LGTM, security checklist satisfied.",
            "submitted_at": "2026-10-31T14:00:00Z",
        },
        {
            "id": 502,
            "user": {"login": "qa_tester"},
            "state": "CHANGES_REQUESTED",
            "body": "Requires regression tests.",
            "submitted_at": "2026-10-31T14:30:00Z",
        },
    ]

    with patch.object(client.session, "get", return_value=mock_resp):
        reviews = client.get_pull_request_reviews("owner", "repo", 15)
        assert len(reviews) == 2
        assert reviews[0]["state"] == "APPROVED"
        assert reviews[1]["state"] == "CHANGES_REQUESTED"


# ---------------------------------------------------------------------------
# Test 9: Handle Rate Limits and Network Failures
# ---------------------------------------------------------------------------

def test_github_api_rate_limit_handling():
    """Verify rate limit triggers descriptive rate-limit error."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"message": "API rate limit exceeded for user"}'
    mock_resp.headers = {"X-RateLimit-Remaining": "0"}

    with patch.object(client.session, "get", return_value=mock_resp):
        with pytest.raises(GitHubClientError) as exc:
            client.get_pull_request("owner", "repo", 15)
        assert "rate limit exceeded" in str(exc.value).lower()


def test_github_network_failure_handling():
    """Verify network timeout is cleanly wrapped in GitHubClientError."""
    client = GitHubClient()
    with patch.object(client.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        with pytest.raises(GitHubClientError) as exc:
            client.get_pull_request("owner", "repo", 15)
        assert "network error" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Test 10: Handle Missing or Unavailable Data Gracefully (Deleted Files & Empty Diffs)
# ---------------------------------------------------------------------------

SAMPLE_DELETED_FILE_DIFF = """diff --git a/legacy_auth.py b/legacy_auth.py
deleted file mode 100644
index 1234567..0000000
--- a/legacy_auth.py
+++ /dev/null
@@ -1,5 +0,0 @@
-def old_login():
-    pass
"""


def test_parse_unified_diff_deleted_file():
    """Verify deleted files (+++ /dev/null) are recognized and parsed."""
    items = parse_unified_diff(SAMPLE_DELETED_FILE_DIFF, commit_sha="abc123")
    assert len(items) == 1
    assert items[0]["file_path"] == "legacy_auth.py"
    assert "def old_login():" in items[0]["snippet"]


def test_parse_unified_diff_empty_or_none():
    """Verify empty or None diff string returns empty list without error."""
    assert parse_unified_diff("") == []
    assert parse_unified_diff("   ") == []
    assert parse_unified_diff(None) == []


def test_null_body_metadata():
    """Verify null body in PR metadata defaults to empty string."""
    client = GitHubClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "title": "PR with no description",
        "body": None,
        "base": {"sha": "b1"},
        "head": {"sha": "h1"},
    }
    with patch.object(client.session, "get", return_value=mock_resp):
        pr = client.get_pull_request("owner", "repo", 1)
        assert pr.description == ""
