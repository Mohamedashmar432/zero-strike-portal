"""Shared vectors for sanitize_repo_url. The identical table lives in the scanner repo's
cmd/zerostrike/portal_support_test.go (TestSanitizeRepoURLVectors); keep them in sync."""

import pytest

from app.core.repo_url import sanitize_repo_url

LEGIT = [
    "https://github.com/o/r",
    "https://github.com/o/r.git",
    "https://github.com/o/r/",
    "https://github.com/my-org/my-repo-name",
    "https://gitlab.com/g/sub/r",
    "https://gitlab.com/g/sub/deeper/r.git",
    "https://dev.azure.com/o/p/_git/r",
    "https://myorg.visualstudio.com/p/_git/r",
    "https://git.example.internal/team/sub/group/repo",
    "https://bitbucket.org/ws/repo",
]
BAD = [
    "https://github.com/ghp_abcdefghijklmnopqrstuvwxyz0123456789/r",
    "https://github.com/o/github_pat_11ABCDEFG0abcdefghijkl",
    "https://github.com/x-access-token/r",
    "https://github.com/o/OAuth2",
    "https://gitlab.com/g/glpat-abcdefghijklmnopqrst/r",
    "https://gitlab.com/g/xoxb-123456789012-abcdef",
    "https://github.com/o/AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "https://github.com/o/r/extra",
    "https://github.com/o",
    "https://bitbucket.org/ws/repo/src",
    "https://dev.azure.com/o/p/r",
    "https://dev.azure.com/o/p/_git/r/extra",
    "https://myorg.visualstudio.com/p/r",
]


@pytest.mark.parametrize("url", LEGIT)
def test_legit_urls_survive(url):
    assert sanitize_repo_url(url) == url


@pytest.mark.parametrize("url", BAD)
def test_credential_looking_paths_are_blanked(url):
    assert sanitize_repo_url(url) is None


def test_userinfo_query_fragment_stripped():
    assert sanitize_repo_url("https://u:p@github.com/o/r?t=1#f") == "https://github.com/o/r"
    assert sanitize_repo_url("https://tok@github.com/o/r?t=1#f") == "https://github.com/o/r"
