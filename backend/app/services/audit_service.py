from app.models.audit_log import AuditLog


async def record(
    action: str,
    *,
    actor_type: str = "user",
    actor_user_id: str | None = None,
    project_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    await AuditLog(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        metadata=metadata or {},
        ip_address=ip_address,
        user_agent=user_agent,
    ).insert()
