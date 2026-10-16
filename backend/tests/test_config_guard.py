import warnings

import pytest
from cryptography.fernet import Fernet

from app.core import security
from app.core.config import Settings


def _make(**kw) -> Settings:
    return Settings(_env_file=None, _secrets_dir=None, **kw)


def test_production_empty_or_short_jwt_raises():
    key = Fernet.generate_key().decode()
    for jwt in ("", "short"):
        with pytest.raises(ValueError, match="JWT_SECRET"):
            _make(app_env="production", jwt_secret=jwt, oauth_encryption_key=key)


def test_production_bad_fernet_key_raises():
    for key in ("", "not-a-fernet-key"):
        with pytest.raises(ValueError, match="OAUTH_ENCRYPTION_KEY"):
            _make(app_env="production", jwt_secret="x" * 40, oauth_encryption_key=key)


def test_default_env_is_production(monkeypatch):
    for name in ("APP_ENV", "JWT_SECRET", "OAUTH_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError):
        _make()


def test_production_valid_values_construct():
    s = _make(app_env="production", jwt_secret="x" * 40, oauth_encryption_key=Fernet.generate_key().decode())
    assert s.app_env == "production"


def test_development_empty_jwt_gets_random_value_and_warns():
    with pytest.warns(UserWarning):
        s = _make(app_env="development", jwt_secret="", oauth_encryption_key=Fernet.generate_key().decode())
    assert len(s.jwt_secret) >= 32


def test_development_with_keys_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warnings.filterwarnings("ignore", message="directory")
        _make(app_env="development", jwt_secret="y" * 40, oauth_encryption_key=Fernet.generate_key().decode())


def test_decrypt_reads_previous_key_and_encrypt_uses_current(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    legacy = Fernet(old.encode()).encrypt(b"hello").decode()
    monkeypatch.setattr(security.settings, "oauth_encryption_key", new)
    monkeypatch.setattr(security.settings, "oauth_encryption_key_previous", [old])
    assert security.decrypt_secret(legacy) == "hello"
    assert Fernet(new.encode()).decrypt(security.encrypt_secret("hi").encode()) == b"hi"


def test_encrypt_without_key_names_the_setting(monkeypatch):
    monkeypatch.setattr(security.settings, "oauth_encryption_key", "")
    with pytest.raises(RuntimeError, match="OAUTH_ENCRYPTION_KEY"):
        security.encrypt_secret("x")
