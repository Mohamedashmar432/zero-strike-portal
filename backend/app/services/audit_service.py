from app.models.audit_log import AuditLog

CATEGORIES = ("privilege", "project", "admin")

# Substrings that mean "someone's access changed" — who can sign in, who holds a key, who is
# a member and with what role. Deliberately matched against the action name rather than
# stored as a field on AuditLog, so the rows already written classify too.
_PRIVILEGE_MARKERS = (
    "login",
    "logout",
    "register",
    "password",
    "user ",
    "member",
    "role",
    "api key",
    "credential",
    "invited",
)


def classify(action: str, project_id: str | None) -> str:
    """Which bucket an audit row belongs to: `privilege`, `project` or `admin`.

    Privilege wins over the other two: a role change inside a project is an access event
    first and a project event second, and the whole reason to separate the buckets is to let
    someone read the access changes without the scan traffic burying them.

    ponytail: substring match on the action name, no stored category. A stored field would
    only classify rows written after it shipped, and would need a backfill to be useful for
    the history that matters most. Revisit if action names stop being human-readable.
    """
    lowered = action.lower()
    if any(marker in lowered for marker in _PRIVILEGE_MARKERS):
        return "privilege"
    return "project" if project_id else "admin"


def is_failure(action: str) -> bool:
    """Whether the action records something that did not succeed. Cross-cutting — a failure
    is still one of the three categories."""
    return "fail" in action.lower()


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
