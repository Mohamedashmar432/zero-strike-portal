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


settings = Settings()
