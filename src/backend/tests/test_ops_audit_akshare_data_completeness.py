import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OPS_DIR = REPO_ROOT / "scripts" / "ops"
sys.path.insert(0, str(OPS_DIR))

import audit_akshare_data_completeness as audit  # noqa: E402


def test_main_fails_before_connecting_without_database_password(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "load_dotenv", lambda _path: None)
    monkeypatch.setattr(sys, "argv", ["audit_akshare_data_completeness.py"])
    for name in ("DATABASE_URL", "AKSHARE_DATA_DATABASE_URL", "DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    def unexpected_connect(_config):
        pytest.fail("database connection attempted without a configured password")

    monkeypatch.setattr(audit, "connect", unexpected_connect)

    with pytest.raises(ValueError, match="DB_PASSWORD"):
        audit.main()


def test_db_password_environment_variable_remains_supported(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "x")
    config = audit.db_config_from_url("DATABASE_URL", audit.META_DB_DEFAULT)
    captured = {}
    monkeypatch.setattr(
        audit.mysql.connector,
        "connect",
        lambda **kwargs: captured.update(kwargs),
    )

    audit.connect(config)

    assert captured["password"] == "x"


def test_database_url_credentials_remain_supported(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL", "mysql+asyncmy://audit-user:x%2Fy@db.example.test:3307/meta_schema"
    )
    config = audit.db_config_from_url("DATABASE_URL", audit.META_DB_DEFAULT)
    captured = {}
    monkeypatch.setattr(
        audit.mysql.connector,
        "connect",
        lambda **kwargs: captured.update(kwargs),
    )

    audit.connect(config)

    assert captured["password"] == "x/y"
    assert captured["host"] == "db.example.test"
    assert captured["port"] == 3307


def test_database_url_without_password_uses_environment_password(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "mysql+asyncmy://audit-user@db.example.test:3307/meta_schema"
    )
    monkeypatch.setenv("DB_PASSWORD", "env%2Fpassword")

    config = audit.db_config_from_url("DATABASE_URL", audit.META_DB_DEFAULT)

    assert config.password == "env%2Fpassword"
    assert config.host == "db.example.test"
    assert config.port == 3307


def test_database_url_without_password_and_environment_password_fails(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "mysql+asyncmy://audit-user@db.example.test:3307/meta_schema"
    )
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="DB_PASSWORD"):
        audit.db_config_from_url("DATABASE_URL", audit.META_DB_DEFAULT)
