import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXTRIO_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    database_path: Path = Path("data/extrio.db")
    database_url: str | None = None
    database_from_pg_env: bool = False
    database_auto_migrate: bool = True
    artifact_path: Path = Path("data/artifacts")
    signing_private_key_path: Path = Path("data/keys/dev-rule-signing-key.pem")
    credential_encryption_key_path: Path = Path("data/keys/dev-credential-encryption.key")
    signing_key_id: str = "signingkey_local_dev_001"
    tenant_id: str = "tenant_demo"
    contracts_path: Path | None = None
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    allow_http_localhost: bool = False
    # Deprecated as a runtime override in v0.6: EXTRIO_ALLOW_HTTP_PUBLIC only
    # supplies the fallback default for the 'allowAnonymousHttp' platform
    # setting (migration 002); the database value managed from the Settings UI
    # wins whenever that row is present.
    allow_http_public: bool = True
    seed_demo: bool = True
    worker_poll_seconds: float = 0.25
    worker_lease_seconds: int = 120
    schedule_poll_seconds: float = 30.0
    auth_enabled: bool = True
    auth_cookie_name: str = "extrio_session"
    auth_cookie_secure: bool = False
    auth_session_hours: int = 12
    auth_login_limit: str = "5/minute"
    metrics_enabled: bool = True
    model_provider: str = "openai"
    model_base_url: str = "https://api.openai.com/v1"
    model_name: str = ""
    model_secret_ref: str = "env:EXTRIO_MODEL_API_KEY"

    @model_validator(mode="after")
    def configure_postgres(self) -> "Settings":
        if not self.database_from_pg_env:
            return self
        if self.database_url:
            raise ValueError("Use either EXTRIO_DATABASE_URL or EXTRIO_DATABASE_FROM_PG_ENV")
        fields = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
        if any(not os.environ.get(field) for field in fields):
            raise ValueError("PostgreSQL configuration requires all five PG environment fields")
        port = os.environ["PGPORT"]
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("PGPORT must be a valid TCP port")
        host = os.environ["PGHOST"]
        if any(character in host for character in "/@?#"):
            raise ValueError("PGHOST must be a hostname or IP address")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        user, password, database = (quote(os.environ[field], safe="") for field in ("PGUSER", "PGPASSWORD", "PGDATABASE"))
        self.database_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def resolve_paths(self, project_dir: Path) -> "Settings":
        updates: dict[str, Path] = {}
        for field in ("database_path", "artifact_path", "signing_private_key_path", "credential_encryption_key_path"):
            value = getattr(self, field)
            updates[field] = value if value.is_absolute() else (project_dir / value).resolve()
        if self.contracts_path is not None:
            updates["contracts_path"] = (
                self.contracts_path
                if self.contracts_path.is_absolute()
                else (project_dir / self.contracts_path).resolve()
            )
        else:
            bundled_contracts = Path(__file__).resolve().parent / "contracts_data"
            repo_contracts = project_dir.parent / "docs" / "contracts"
            updates["contracts_path"] = bundled_contracts if bundled_contracts.is_dir() else repo_contracts
        return self.model_copy(update=updates)


@lru_cache
def get_settings() -> Settings:
    project_dir = Path(__file__).resolve().parents[2]
    return Settings().resolve_paths(project_dir)
