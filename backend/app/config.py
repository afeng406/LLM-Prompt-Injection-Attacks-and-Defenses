from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    llm_provider: str = "longcat"
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.longcat.chat/openai/v1"
    llm_model: str = "LongCat-2.5-Preview"
    llm_timeout_seconds: float = Field(default=60, gt=0, le=180)
    llm_max_tokens: int = Field(default=768, ge=128, le=8192)
    llm_temperature: float = Field(default=0, ge=0, le=2)

    @property
    def configured(self) -> bool:
        return self.llm_api_key.get_secret_value() not in (
            "",
            "replace-with-local-secret",
        )

    def public_config(self) -> dict:
        return {
            "provider": self.llm_provider,
            "base_url": self.llm_base_url,
            "model": self.llm_model,
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
            "timeout_seconds": self.llm_timeout_seconds,
            "max_retries": 0,
        }
