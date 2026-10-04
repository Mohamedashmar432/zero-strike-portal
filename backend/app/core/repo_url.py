"""Syntax-only repo URL check, shared by request schemas (write time, no DNS) and
cloud_scan_service.validate_repo_url (clone time, adds DNS/IP vetting)."""

from urllib.parse import ParseResult, urlparse


def check_repo_url_syntax(repo_url: str) -> ParseResult:
    """Return the parsed URL, or raise ValueError. A leading '-' would be read by git as an option
    (`--upload-pack=<cmd>` is command execution), and userinfo can smuggle a different host past a
    naive reader, so both are refused along with any non-http(s) scheme."""
    if repo_url.startswith("-"):
        raise ValueError("repo_url must not start with '-'")
    parsed = urlparse(repo_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("repo_url must be an http or https URL")
    if not parsed.hostname:
        raise ValueError("repo_url has no host")
    # A bare username is allowed: Azure DevOps' remoteUrl is always `https://{org}@dev.azure.com/...`.
    # `hostname` already strips userinfo, so the DNS/IP check still vets the real host.
    if parsed.password is not None:
        raise ValueError("repo_url must not contain credentials")
    try:
        _ = parsed.port  # raises ValueError on a malformed port
    except ValueError:
        raise ValueError("repo_url has an invalid port")
    return parsed
