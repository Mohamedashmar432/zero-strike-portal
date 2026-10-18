"""Syntax-only repo URL check, shared by request schemas (write time, no DNS) and
cloud_scan_service.validate_repo_url (clone time, adds DNS/IP vetting)."""

import ipaddress
import re
import socket
from urllib.parse import ParseResult, urlparse, urlsplit, urlunsplit


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


def resolve_vetted_ips(hostname: str) -> list[str]:
    """DNS-resolve `hostname` and reject any result that isn't globally routable (SSRF +
    cloud-metadata 169.254.169.254 + CGNAT 100.64/10 defense). Returns the vetted IP strings
    so a caller can pin a later connection to them against DNS-rebinding. Raises ValueError."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError("host does not resolve")
    vetted: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]
        ip = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ValueError("host resolves to a disallowed address")
        if raw not in vetted:
            vetted.append(raw)
    if not vetted:
        raise ValueError("host does not resolve")
    return vetted


_TOKEN_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "glpat-", "gldt-", "xox")
_TOKEN_SEGMENTS = {"x-access-token", "oauth2"}
_ENTROPY_SEGMENT = re.compile(r"[A-Za-z0-9_-]{32,}")


def _segment_is_token(seg: str) -> bool:
    low = seg.lower()
    if low.startswith(_TOKEN_PREFIXES) or low in _TOKEN_SEGMENTS:
        return True
    return bool(
        _ENTROPY_SEGMENT.fullmatch(seg)
        and any(c.isupper() for c in seg)
        and any(c.islower() for c in seg)
        and any(c.isdigit() for c in seg)
    )


def _path_is_plausible(host: str, segs: list[str]) -> bool:
    """A repo path with a token pasted into it (https://github.com/ghp_xxx/repo) or too many segments
    for hosts whose layout is fixed. Self-hosted hosts and gitlab.com (subgroups) get no cap."""
    if any(_segment_is_token(s) for s in segs):
        return False
    if host in ("github.com", "bitbucket.org"):
        return len(segs) == 2
    if host == "dev.azure.com":
        return len(segs) == 4 and segs[2] == "_git"
    if host.endswith(".visualstudio.com"):
        return len(segs) >= 2 and segs[-2] == "_git"
    return True


def sanitize_repo_url(raw) -> str | None:
    """Display-safe form of a scanner-reported repo URL, or None. Strips userinfo/query/fragment
    (a token can ride in any of them), syntax-checks, and blanks the whole URL when the path itself
    looks like it carries a credential. Never raises: metadata must not fail a scan upload."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parts = urlsplit(raw.strip())
        cleaned = urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, "", ""))
        check_repo_url_syntax(cleaned)
    except ValueError:
        return None
    segs = [s for s in parts.path.split("/") if s]
    if segs and segs[-1].lower().endswith(".git"):
        segs[-1] = segs[-1][:-4]
    if not _path_is_plausible((urlsplit(cleaned).hostname or "").lower(), segs):
        return None
    return cleaned
