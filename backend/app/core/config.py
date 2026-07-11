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


settings = Settings()
