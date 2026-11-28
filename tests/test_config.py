"""Settings tests. _env_file=None keeps tests independent of any local .env.

NOTE: `_env_file` is the documented BaseSettings __init__ kwarg (pydantic-settings
docs, "Dotenv support"). Pylance/pyright synthesizes __init__ from declared fields
only, so it falsely reports "No parameter named '_env_file'" — hence the narrow
type: ignore comments. Do NOT rename to `env_file`: that kwarg is silently ignored
(extra="ignore") and the real .env would leak into tests.
"""

from health_interop.config import Settings


def test_defaults_without_dotenv() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "local"
    assert s.log_level == "INFO"
    assert s.postgres_host == "127.0.0.1"
    assert s.postgres_port == 5432


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DB", "test_db")
    monkeypatch.setenv("POSTGRES_USER", "test_user")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.postgres_db == "test_db"
    assert s.postgres_user == "test_user"


def test_database_url_components_and_escaping() -> None:
    s = Settings(_env_file=None, postgres_password="p@ss:word")  # type: ignore[call-arg]
    url = s.database_url
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "127.0.0.1"
    assert url.port == 5432
    assert url.database == "interop"
    assert url.password == "p@ss:word"
    assert "p@ss:word" not in url.render_as_string(hide_password=False)


def test_secrets_are_masked_in_repr() -> None:
    s = Settings(_env_file=None, postgres_password="super-secret-value")  # type: ignore[call-arg]
    assert "super-secret-value" not in repr(s)
