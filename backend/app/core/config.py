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
    # Caps scanner goroutine parallelism (default is NumCPU). Two concurrent cloud scans each
    # spawning NumCPU workers can push peak memory past a constrained container's limit and get
    # SIGKILL'd by the OOM killer ("scanner exited -9") on large/vendor-heavy repos. Lower this
    # if that still happens on your deployment's container size; raise it if scans are slow and
    # memory headroom is available.
    scanner_max_workers: int = 2
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

    # AI Auto-Fix / remediation (see ai_remediation_service / ai_remediation_apply_service, docs/AI_AUTOFIX_DESIGN.md).
    # A third Mongo-backed queue peer of the scan + AI-analysis queues; heavier than analysis (a
    # multi-step tool-calling loop, plus a clone + double scan on apply), so its own conservative knobs.
    max_concurrent_remediation_jobs: int = 1
    remediation_job_timeout_seconds: int = 600  # whole-job wall clock; the reap window uses this * multiplier
    remediation_queue_stuck_multiplier: int = 3
    # Agent loop bounds (per finding). Any exhaustion yields a can_fix=False proposal, never a job failure.
    remediation_agent_max_steps: int = 12  # tool-call iterations
    remediation_agent_token_budget: int = 60000  # cumulative prompt+completion per finding run
    remediation_agent_wall_clock_seconds: int = 180  # per-finding asyncio.wait_for
    remediation_max_invalid_steps: int = 2  # consecutive no-tool/bad-arg responses before fail-fast
    remediation_max_findings_per_job: int = 20
    # Only can_fix=True AND confidence_score >= this surfaces as actionable (CLI parity, gate at read time).
    remediation_confidence_threshold: float = 80.0
    remediation_max_file_bytes: int = 200_000  # read_file cap
    remediation_max_excerpt_lines: int = 400
    remediation_llm_request_timeout_seconds: int = 90  # per acompletion; tool calls run longer than analysis
    remediation_max_output_tokens: int = 4000  # per-call max_tokens
    # Providers whose tool-calling is reliable enough to drive the agent. Excludes lmstudio/custom
    # (local models routinely ignore `tools` and just emit prose). The trigger 409s if the active
    # provider isn't here or litellm.supports_function_calling() is False for its model.
    remediation_tool_capable_providers: set[str] = {
        "anthropic",
        "openai",
        "openrouter",
        "groq",
        "kimi",
        "nvidia_nim",
        "gemini",
    }
    # Post-draft critique pass (remediation_critic.py): one extra JSON completion per *fixable*
    # finding that reviews the drafted patch before a human sees it. Deterministic triage already
    # removed the hopeless findings, so this only costs on drafts worth reviewing. Kill switch:
    # setting this False leaves the pipeline exactly as it was pre-critic.
    remediation_critic_enabled: bool = True
    # A "revise" verdict feeds the critic's issues back through the agent's existing revision_note
    # channel. 1 keeps the worst-case per-finding cost bounded at two agent runs; the per-finding
    # wall clock (remediation_agent_wall_clock_seconds) still applies to each run separately.
    remediation_critic_max_redrafts: int = 1
    remediation_critic_max_output_tokens: int = 2000  # a verdict + a few bullets, not code
    # Skip the critique for a dependency-bump patch: the whole change is one version string in a
    # manifest, and the target version comes from the scanner's advisory data rather than the
    # model's imagination — so there is no drafted *logic* for a reviewer to be skeptical about.
    # SCA findings are typically the most numerous class, so this is where the pass costs most and
    # buys least. The deterministic apply gate (baseline scan -> patch -> re-scan) still runs, as
    # does human approval. Set False to critique every fixable draft.
    remediation_critic_skip_dependency_bumps: bool = True

    # Compliance audits (compliance_queue_service / compliance_audit_service). A fourth
    # Mongo-backed queue peer. Cheap by default — the control evaluation is a pure in-memory
    # pass over the project's findings; only the optional AI narrative costs anything, which
    # is why the concurrency here is higher than remediation's.
    max_concurrent_compliance_audits: int = 2
    compliance_audit_timeout_seconds: int = 300
    compliance_queue_stuck_multiplier: int = 3
    # Caps the evidence set pulled into memory for one audit (findings sorted by
    # priority_score desc). A project with more matching findings than this still gets an
    # accurate pass/fail — the highest-priority evidence is what drives it — but the audit is
    # flagged findings_truncated so the UI can say so rather than implying full coverage.
    compliance_max_findings: int = 5000
    # Per-control evidence rows persisted on the audit document. The exact match count is
    # kept separately (evidence_total), so this only bounds document size, not correctness.
    compliance_max_evidence_per_control: int = 25
    # One narrative call per framework covers its failing/partial controls; this bounds that
    # call's output. Explanations + remediation prose, no code.
    compliance_ai_max_output_tokens: int = 3000
    # Controls sent to the LLM in one framework's narrative call. Beyond this the remainder
    # keep their deterministic rationale with no AI prose (never a job failure).
    compliance_ai_max_controls_per_call: int = 25

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
