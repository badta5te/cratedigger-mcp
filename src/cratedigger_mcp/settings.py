"""Configuration read from the environment."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cratedigger_mcp.discogs import Currency


class Settings(BaseSettings):
    """Runtime settings. Only `DISCOGS_TOKEN` is required."""

    model_config = SettingsConfigDict(extra="ignore")

    discogs_token: SecretStr
    # The currency prices are shown in unless a tool call asks for another (DISCOGS_CURRENCY).
    discogs_currency: Currency = "EUR"

    @field_validator("discogs_token")
    @classmethod
    def _token_must_not_be_blank(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("DISCOGS_TOKEN is empty")
        return value
