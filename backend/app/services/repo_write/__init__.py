class RepoWriteError(Exception):
    """A GitHub/Azure DevOps write API call (create PR) failed -- bad/insufficient-scope token, no
    access, provider outage. Message is safe to surface (never includes the raw token)."""
