from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", secrets_dir="/run/secrets")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "zerostrike"

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    artifact_storage_path: str = "./data/artifacts"

    cors_origins: list[str] = ["http://localhost:3000"]

    # ponytail: demo-only status transitions until Sprint 3 wires real scan execution; flip off before a real cutover.
    enable_mock_scan_endpoints: bool = True

    # Server-side (cloud) scan execution — the CGO-enabled scanner binary baked into the image.
    scanner_binary_path: str = "/usr/local/bin/zerostrike"
    scan_timeout_seconds: int = 900
    max_concurrent_cloud_scans: int = 2
    clone_workdir_path: str = "/tmp/zs-clones"  # ephemeral; never the durable artifacts volume


settings = Settings()
