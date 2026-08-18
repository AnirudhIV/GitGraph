"""Application configuration, loaded from environment variables.

Connection details for CognoDB must never be hard-coded or committed;
they are read here from the environment (see .env.example).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    neo4j_uri: str = "bolt+s://localhost:7687"
    neo4j_user: str = "cognodb"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
