from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", secrets_dir="/run/secrets")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "zerostrike"

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    cors_origins: list[str] = ["http://localhost:3000"]

    # Server-side (cloud) scan execution. The scanner runs as a subprocess — no Docker at runtime.
    # Point scanner_binary_path at a local `zerostrike`/`zerostrike.exe` (dev) or the container binary.
    scanner_binary_path: str = "zerostrike"
    scan_timeout_seconds: int = 900
    max_concurrent_cloud_scans: int = 2
    clone_workdir_path: str = ""  # empty => OS temp dir/zs-clones (cross-platform)

    # Mongo-backed cloud-scan queue (see scan_queue_service).
    queue_poll_interval_seconds: int = 5
    queue_stuck_multiplier: int = 3  # a "running" scan idle longer than this * scan_timeout_seconds is reaped

    # AI analysis (see ai_job_queue_service / ai_analysis_service) — mirrors the cloud-scan queue's
    # Mongo-backed claim/reap pattern, just bounded by different concurrency/timeout knobs since an
    # AI job is an LLM call, not a clone+scan subprocess.
    max_concurrent_ai_jobs: int = 3
    ai_job_timeout_seconds: int = 300
    ai_queue_stuck_multiplier: int = 3
    # Per-attempt cap passed to litellm.acompletion — without this, a hung/slow provider
    # connection blocks the request indefinitely (litellm/httpx default to no timeout).
    ai_llm_request_timeout_seconds: int = 60
    # Bounds concurrent per-rule-group LLM calls within a single job (ai_analysis_service).
    ai_analysis_concurrency: int = 3
    # Caps how many of a scan's findings (sorted by priority_score desc) get analyzed per scan-level job.
    ai_analysis_max_findings_per_scan: int = 200
    # A rule_id group is chunked into batches of this many findings per LLM call so a huge group
    # (a rule firing across hundreds of files) doesn't overflow a small local model's context.
    # Smaller for local providers — shorter prompt = faster, more reliable local response (mirrors
    # zero-strike-cli's SecurityAgentRunner batch sizing).
    ai_analysis_local_batch_size: int = 8
    ai_analysis_cloud_batch_size: int = 40
    # Caps the LLM's output on an enrichment call so a small local model doesn't run past its own
    # (often tiny) default output limit mid-JSON and truncate the response — the root cause of
    # findings silently going un-enriched. Generous: one enrichment object per rule in a batch.
    ai_analysis_max_output_tokens: int = 4000
    # Providers served by a local, resource-constrained runtime (LM Studio / a custom self-hosted
    # endpoint) — get the smaller batch size above.
    ai_analysis_local_providers: set[str] = {"lmstudio", "custom"}

    # GitHub/Azure DevOps OAuth repo import (connections.py, connection_service.py).
    github_client_id: str = ""
    github_client_secret: str = ""
    azure_devops_client_id: str = ""
    azure_devops_client_secret: str = ""
    # Fernet key for encrypting OAuth tokens at rest. Fixed dev default (not regenerated per-restart,
    # unlike jwt_secret's throwaway-dev-value pattern) because a rotating key would make previously
    # encrypted Mongo rows undecryptable. Override in production via env/secrets file.
    oauth_encryption_key: str = "3RmU3vG6nF1sVw8lXe0aP7wQyKzD2bT9cH4jN6oI5uY="
    backend_public_url: str = "http://localhost:8000"  # used to build each provider's redirect_uri
    frontend_origin: str = "http://localhost:3000"  # where /connections/{provider}/callback redirects to

    # SMTP (email_service) — used by the forgot-password flow to send reset links. Empty smtp_host
    # (the dev default) means email_service.send_email() logs a warning and no-ops instead of trying
    # to connect, so local/dev works without SMTP configured.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from_address: str = "noreply@zerostrike.dev"

    # Password reset tokens (auth_service.request_password_reset / reset_password).
    password_reset_token_ttl_minutes: int = 30
    # How long past revocation/expiry a refresh token record is kept before pruning
    # (auth_service._prune_refresh_tokens) — bounds unbounded growth of User.refresh_tokens.
    refresh_token_retention_days: int = 7

    # In-memory sliding-window rate limits (app.core.rate_limit) for auth endpoints.
    rate_limit_login_max_attempts: int = 10
    rate_limit_login_window_seconds: int = 60
    rate_limit_register_max_attempts: int = 5
    rate_limit_register_window_seconds: int = 60
    rate_limit_forgot_password_max_attempts: int = 5
    rate_limit_forgot_password_window_seconds: int = 300


settings = Settings()
