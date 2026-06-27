from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    groq_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    groq_model: str = "llama-3.3-70b-versatile"
    max_concurrency: int = 8
    max_judge_calls: int | None = None
    judge_temperature: float = 0.0
    judge_max_tokens: int = 500
    openai_input_cost_per_m: float = 0.15
    openai_output_cost_per_m: float = 0.60
    groq_input_cost_per_m: float = 0.0
    groq_output_cost_per_m: float = 0.0

    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    def has_groq(self) -> bool:
        return bool(self.groq_api_key)
