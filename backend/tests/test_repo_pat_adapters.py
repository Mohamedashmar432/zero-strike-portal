import base64

from app.services.repo_pat.azure_devops import _auth_headers as ado_auth_headers
from app.services.repo_pat.github import _auth_headers as gh_auth_headers


def test_github_auth_headers_use_bearer():
    headers = gh_auth_headers("my-pat")
    assert headers["Authorization"] == "Bearer my-pat"


def test_azure_devops_auth_headers_use_basic_not_bearer():
    """Azure DevOps PATs authenticate with HTTP Basic (empty username, PAT as password) — never
    Bearer. Reusing the OAuth adapter's Bearer scheme here is exactly the bug that prompted a
    dedicated PAT-auth module: regression test pinning the header format down explicitly."""
    headers = ado_auth_headers("my-pat")
    expected = base64.b64encode(b":my-pat").decode()
    assert headers["Authorization"] == f"Basic {expected}"
    assert "Bearer" not in headers["Authorization"]
