from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List
import os


class Settings(BaseSettings):
    discord_token: str = Field(..., env="DISCORD_TOKEN")
    discord_client_id: str = Field("", env="DISCORD_CLIENT_ID")
    discord_client_secret: str = Field("", env="DISCORD_CLIENT_SECRET")

    database_url: str = Field(..., env="DATABASE_URL")
    database_url_sync: str = Field("", env="DATABASE_URL_SYNC")

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Railway provides postgresql://, asyncpg needs postgresql+asyncpg://"""
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    port: int = Field(8000, env="PORT")
    api_secret_key: str = Field("changeme_at_least_32_chars_long_!", env="API_SECRET_KEY")
    api_algorithm: str = Field("HS256", env="API_ALGORITHM")
    access_token_expire_minutes: int = Field(1440, env="ACCESS_TOKEN_EXPIRE_MINUTES")

    admin_role_id: int = Field(1514289625131258048, env="ADMIN_ROLE_ID")
    whitelist_role_id: int = Field(152326964767844359, env="WHITELIST_ROLE_ID")
    log_channel_id: int = Field(0, env="LOG_CHANNEL_ID")
    alert_channel_id: int = Field(0, env="ALERT_CHANNEL_ID")

    allowed_origins: str = Field("*", env="ALLOWED_ORIGINS")

    environment: str = Field("production", env="ENVIRONMENT")
    debug: bool = Field(False, env="DEBUG")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_file: str = Field("logs/bot.log", env="LOG_FILE")

    @property
    def cors_origins(self) -> List[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
