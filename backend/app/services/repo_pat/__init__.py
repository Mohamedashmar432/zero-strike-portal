class RepoPatError(Exception):
    """Raised when a GitHub/Azure DevOps API call made with a user-supplied PAT fails (bad token, no
    access, rate limited, provider outage) — message is safe to surface as a 400, never includes the
    raw token."""
