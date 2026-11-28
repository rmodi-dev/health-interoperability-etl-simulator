"""Application settings via pydantic-settings.

Precedence: real environment variables > .env file > defaults.
Secrets use SecretStr so they never appear in logs or repr output.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    tz: str = "UTC"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "interop"
    postgres_user: str = "interop"
    postgres_password: SecretStr = SecretStr("")

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: SecretStr = SecretStr("")

    mllp_host: str = "127.0.0.1"
    mllp_port: int = 2575

    lis2a2_host: str = "127.0.0.1"
    lis2a2_port: int = 3000

    @property
    def database_url(self) -> URL:
        """SQLAlchemy URL for psycopg v3. URL.create escapes credentials safely."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
