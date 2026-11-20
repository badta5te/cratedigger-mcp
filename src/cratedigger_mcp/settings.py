"""Configuration read from the environment."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Only `DISCOGS_TOKEN` is required."""

    model_config = SettingsConfigDict(extra="ignore")

    discogs_token: SecretStr

    @field_validator("discogs_token")
    @classmethod
    def _token_must_not_be_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("DISCOGS_TOKEN is empty")
        return value
