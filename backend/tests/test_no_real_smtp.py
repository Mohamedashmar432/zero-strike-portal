from app.core.config import settings


def test_suite_never_has_a_real_smtp_relay_or_key_vault():
    # conftest blanks these so a developer's local .env can't make tests send real mail.
    assert settings.smtp_host == ""
    assert settings.smtp_password == ""
    assert settings.azure_key_vault_url == ""
