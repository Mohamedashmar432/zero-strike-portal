"""Signup-approval email templates: built-in defaults plus admin overrides.

An admin may rewrite the subject and body of each email in Settings > Notifications. Overrides
live on `WorkspaceSettings.email_templates`; a missing key falls back to the default here, so
"reset to default" is just deleting the override.

Rendering is a plain `{placeholder}` substitution over a fixed per-template whitelist — not
`str.format` — so an admin's text cannot reach attributes or raise KeyError, and a typo like
`{nmae}` is rejected when saved (`unknown_placeholders`) instead of being mailed out literally.
Values are HTML-escaped in the HTML part: an applicant controls `{name}`, and it lands in an
email an admin will open.
"""

import re
from dataclasses import dataclass
from html import escape

_TOKEN = re.compile(r"\{(\w+)\}")
_URL = re.compile(r"(https?://[^\s<]+)")


@dataclass(frozen=True)
class EmailTemplate:
    key: str
    label: str
    description: str
    placeholders: tuple[str, ...]
    subject: str
    body: str


TEMPLATES: tuple[EmailTemplate, ...] = (
    EmailTemplate(
        key="signup_requested",
        label="New signup request (to admins)",
        description="Sent to the admins chosen as signup reviewers when someone registers.",
        placeholders=("name", "email", "action_url"),
        subject="New access request from {name}",
        body=(
            "{name} ({email}) has registered for thinkShield Portal and is waiting for approval.\n\n"
            "Review the request:\n{action_url}"
        ),
    ),
    EmailTemplate(
        key="signup_approved",
        label="Request approved (to applicant)",
        description="Sent to the person when an admin approves their signup.",
        placeholders=("name", "action_url"),
        subject="Your thinkShield Portal access has been approved",
        body=(
            "Hello {name},\n\n"
            "An administrator has approved your access to thinkShield Portal. "
            "You can sign in now:\n{action_url}"
        ),
    ),
    EmailTemplate(
        key="signup_welcome",
        label="Welcome (open signup)",
        description="Sent to the person right after they register when no approval is required.",
        placeholders=("name", "action_url"),
        subject="Welcome to thinkShield Portal",
        body="Hello {name},\n\nYour thinkShield Portal account is ready. Sign in here:\n{action_url}",
    ),
    EmailTemplate(
        key="signup_rejected",
        label="Request declined (to applicant)",
        description="Sent to the person when an admin declines their signup.",
        placeholders=("name", "reason"),
        subject="Your thinkShield Portal access request",
        body=(
            "Hello {name},\n\n"
            "Your request for access to thinkShield Portal was not approved.\n\n"
            "{reason}\n\n"
            "If you believe this is a mistake, please contact your administrator."
        ),
    ),
)

BY_KEY = {t.key: t for t in TEMPLATES}

SUBJECT_MAX = 200
BODY_MAX = 5000


def unknown_placeholders(key: str, *texts: str) -> list[str]:
    allowed = set(BY_KEY[key].placeholders)
    found = {m for t in texts for m in _TOKEN.findall(t)}
    return sorted(found - allowed)


def _fill(text: str, values: dict[str, str], *, html: bool) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in values:
            return m.group(0)
        v = values[m.group(1)]
        return escape(v) if html else v

    return _TOKEN.sub(sub, text)


def resolve(key: str, overrides: dict[str, dict[str, str]]) -> tuple[str, str]:
    """(subject, body) for `key`: the admin's override where set and non-blank, else default."""
    default = BY_KEY[key]
    custom = overrides.get(key) or {}
    return (custom.get("subject") or default.subject, custom.get("body") or default.body)


def render(
    key: str, overrides: dict[str, dict[str, str]], values: dict[str, str]
) -> tuple[str, str, str]:
    """Returns (subject, text_body, html_body)."""
    subject_t, body_t = resolve(key, overrides)
    # A subject is a header: collapse any newline an applicant's name could smuggle in.
    subject = " ".join(_fill(subject_t, values, html=False).split())
    text = re.sub(r"\n{3,}", "\n\n", _fill(body_t, values, html=False)).strip()
    html_body = re.sub(r"\n{3,}", "\n\n", _fill(body_t, values, html=True)).strip()
    html_body = _URL.sub(r'<a href="\1">\1</a>', html_body).replace("\n", "<br>")
    return subject, text, f"<div>{html_body}</div>"
