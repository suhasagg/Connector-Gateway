from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    env: str = "dev"
    database_url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    request_timeout_seconds: float = 20.0
    max_retries: int = 2
    cli_allowlist: str = "git,kubectl,python"
    mcp_server_url: str = "http://localhost:8081"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
