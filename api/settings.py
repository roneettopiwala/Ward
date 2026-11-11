from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    cors_origins: list[str] = ["http://localhost:3000"]
    anthropic_api_key: str = ""
    llm_model: str = "anthropic/claude-opus-5-5"
    # Writes persona backstories, once per neighbourhood.
    persona_model: str = "anthropic/claude-sonnet-5-5"
    # Turns typed prompts into proposals (fast; called on every Preview and Refine).
    parse_model: str = "anthropic/claude-haiku-5-5"
    # Every persona reaction (fast, called in parallel). Stored on each persona.
    reaction_model: str = "anthropic/claude-haiku-5-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
