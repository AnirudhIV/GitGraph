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

    # Half-life (in days) for the recency-weighted hotspot score
    # (risk_score_recent): a commit/coupling this many days old contributes
    # half the weight of one happening now, decaying exponentially from
    # there. See queries.py's HOTSPOTS_* for how this feeds the formula.
    hotspot_recency_half_life_days: float = 180.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
