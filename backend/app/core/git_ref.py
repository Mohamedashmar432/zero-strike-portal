"""Branch-name validation shared by every place a user-supplied branch reaches `git`."""

import re

_BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]+")
MAX_BRANCH_LENGTH = 255


def validate_branch_name(value: str) -> str:
    """Return `value` unchanged if it is safe to pass to git as a branch, else raise ValueError.

    Rejects a leading `-` (could be read as an option), `..`, anything outside the conservative
    character set, and names over 255 characters."""
    if (
        not value
        or len(value) > MAX_BRANCH_LENGTH
        or not _BRANCH_RE.fullmatch(value)
        or value.startswith("-")
        or ".." in value
    ):
        raise ValueError("invalid branch name")
    return value
