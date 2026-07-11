class OAuthProviderError(Exception):
    """Raised when a provider's OAuth exchange or API call fails; message is safe to surface to the
    caller as a generic 4xx (never includes the client secret or raw token)."""
