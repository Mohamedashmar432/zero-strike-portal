import app.services.email_service as email_service


class _FakeSMTP:
    """Stand-in for smtplib.SMTP — records constructor args and every call made on it."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args = None
        self.sendmail_args = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addrs, message):
        self.sendmail_args = (from_addr, to_addrs, message)


def _reset_fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)


def test_send_email_noop_when_smtp_host_unset(monkeypatch, caplog):
    monkeypatch.setattr(email_service.settings, "smtp_host", "")
    _reset_fake_smtp(monkeypatch)

    with caplog.at_level("WARNING"):
        email_service.send_email("user@example.com", "Subject", "body text")

    assert _FakeSMTP.instances == []
    assert any("smtp" in r.message.lower() for r in caplog.records)


def test_send_email_connects_and_sends_with_tls_and_login(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_port", 2525)
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", True)
    monkeypatch.setattr(email_service.settings, "smtp_username", "svc-user")
    monkeypatch.setattr(email_service.settings, "smtp_password", "svc-pass")
    monkeypatch.setattr(email_service.settings, "smtp_from_address", "noreply@example.com")
    _reset_fake_smtp(monkeypatch)

    email_service.send_email("user@example.com", "Hi there", "plain body", "<p>html body</p>")

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.port == 2525
    assert smtp.starttls_called is True
    assert smtp.login_args == ("svc-user", "svc-pass")
    from_addr, to_addrs, message = smtp.sendmail_args
    assert from_addr == "noreply@example.com"
    assert to_addrs == ["user@example.com"]
    assert "plain body" in message
    assert "html body" in message
    assert "Hi there" in message


def test_send_email_skips_starttls_when_tls_disabled(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", False)
    monkeypatch.setattr(email_service.settings, "smtp_username", "")
    monkeypatch.setattr(email_service.settings, "smtp_password", "")
    _reset_fake_smtp(monkeypatch)

    email_service.send_email("user@example.com", "Subject", "body")

    smtp = _FakeSMTP.instances[0]
    assert smtp.starttls_called is False


def test_send_email_skips_login_when_credentials_empty(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", False)
    monkeypatch.setattr(email_service.settings, "smtp_username", "")
    monkeypatch.setattr(email_service.settings, "smtp_password", "")
    _reset_fake_smtp(monkeypatch)

    email_service.send_email("user@example.com", "Subject", "body")

    smtp = _FakeSMTP.instances[0]
    assert smtp.login_args is None


def test_send_email_skips_login_when_only_username_set(monkeypatch):
    # Both username AND password must be non-empty to attempt login.
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", False)
    monkeypatch.setattr(email_service.settings, "smtp_username", "svc-user")
    monkeypatch.setattr(email_service.settings, "smtp_password", "")
    _reset_fake_smtp(monkeypatch)

    email_service.send_email("user@example.com", "Subject", "body")

    smtp = _FakeSMTP.instances[0]
    assert smtp.login_args is None


def test_send_email_text_only_has_no_html_part(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", False)
    monkeypatch.setattr(email_service.settings, "smtp_username", "")
    monkeypatch.setattr(email_service.settings, "smtp_password", "")
    _reset_fake_smtp(monkeypatch)

    email_service.send_email("user@example.com", "Subject", "plain only body")

    _from_addr, _to_addrs, message = _FakeSMTP.instances[0].sendmail_args
    assert "plain only body" in message
    assert "text/html" not in message


def test_send_password_reset_email_includes_reset_url_in_both_bodies(monkeypatch):
    captured = {}

    def fake_send_email(to_address, subject, text_body, html_body=None):
        captured["to_address"] = to_address
        captured["subject"] = subject
        captured["text_body"] = text_body
        captured["html_body"] = html_body

    monkeypatch.setattr(email_service, "send_email", fake_send_email)

    reset_url = "https://portal.example.com/reset-password?token=abc123"
    email_service.send_password_reset_email("user@example.com", reset_url, ttl_minutes=30)

    assert captured["to_address"] == "user@example.com"
    assert captured["subject"]  # non-empty
    assert "password" in captured["subject"].lower()
    assert reset_url in captured["text_body"]
    assert reset_url in captured["html_body"]
    assert "30 minutes" in captured["text_body"]
    assert "30 minutes" in captured["html_body"]
