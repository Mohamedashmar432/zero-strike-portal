"""Unit tests for secret_redaction.redact (no DB, no client)."""

from app.services.secret_redaction import PLACEHOLDER, redact


def test_redacts_known_credential_shapes():
    text = "token = 'ghp_" + "a" * 36 + "'\nkey = AKIA" + "A" * 16
    out = redact(text)
    assert "ghp_" not in out
    assert "AKIA" not in out
    assert PLACEHOLDER in out


def test_high_entropy_assignment_redacted_but_plain_value_kept():
    secret = "aws_secret = 'k8Jf93jsl2mQpZx7Tn4vBw1Rd0Ye6Uc9Ab2'"  # long + random
    benign = "api_key = 'default'"  # short, low entropy
    out = redact(secret + "\n" + benign)
    assert PLACEHOLDER in out.splitlines()[0]
    assert out.splitlines()[1] == benign  # untouched


def test_preserves_line_count_and_known_secret_lines():
    text = "line1\nSUPER_SECRET_VALUE_HERE\nline3\n"
    out = redact(text, known_secret_lines={2})
    lines = out.splitlines()
    assert len(lines) == 3
    assert lines[0] == "line1"
    assert lines[1] == PLACEHOLDER
    assert lines[2] == "line3"
    assert out.endswith("\n")  # trailing newline preserved
