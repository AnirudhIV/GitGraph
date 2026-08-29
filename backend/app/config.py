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

    # Minimum ownership share (commits by this author on a file / total
    # commits on that file) before the file counts toward an author's
    # criticality score at all. Originally borrowed riskTier()'s "critical"
    # cutoff (0.75, frontend/src/lib/riskColor.ts) since that number was
    # already established elsewhere -- but that threshold was designed to
    # grade a *score's severity*, not to gate *inclusion* in a list, and at
    # 0.75 only 8 of this repo's 872 authors ever qualified at all (most
    # files in a long-running, well-collaborated repo get touched by many
    # contributors, so few people concentrate that heavily on any one
    # file). Lowered to 0.5 -- "did most of the work on this file" -- to
    # surface more real single-points-of-failure without losing the "this
    # person is genuinely the primary owner" meaning.
    author_criticality_concentration_threshold: float = 0.5

    # Multiplicative boost on a file's contribution to its author's
    # criticality score when that author is the *only* person who has ever
    # committed to it (share == 1.0). A deliberate exception to keeping
    # flags separate from the score (see the comment above
    # GraphNode.sole_owned in schemas.py): sole ownership is severe enough
    # to warrant folding into the number itself, not just flagged beside it.
    author_criticality_sole_ownership_boost: float = 0.5

    # Flat amount added to criticality_score for every file an author
    # solely owns (share == 1.0), on top of -- not instead of -- the
    # risk_score-weighted term, and regardless of whether that file has a
    # risk_score at all. A stable, low-churn, rarely-coupled file the
    # hotspot gate would never score is exactly the file least likely to
    # ever get a second contributor, so without this floor, sole ownership
    # of it silently contributed nothing to the score. See the comment
    # above PRECOMPUTE_AUTHOR_CRITICALITY in queries.py for the full
    # reasoning.
    author_criticality_sole_ownership_baseline: float = 0.1

    # An author is flagged stale (in API responses only -- never blended
    # into criticality_score) if their last commit is older than this many
    # days. Computed at request time from the already-precomputed
    # last_commit_at, not baked in at ingest time, since "is this still
    # true" drifts with the wall clock, not with the graph.
    author_stale_after_days: float = 180.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
