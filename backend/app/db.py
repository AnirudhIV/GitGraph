"""CognoDB (Neo4j-protocol) driver lifecycle and query execution helpers.

CognoDB speaks openCypher over Bolt, so the official `neo4j` Python driver
talks to it with no custom SDK. All queries are parameterised here -- no
string-concatenated Cypher anywhere in the app.
"""
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.config import get_settings

logger = logging.getLogger("app.db")

_driver: Driver | None = None


class DatabaseUnavailableError(RuntimeError):
    """Raised when CognoDB cannot be reached or a query fails."""


def init_driver() -> None:
    global _driver
    settings = get_settings()
    _driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def verify_connectivity() -> bool:
    if _driver is None:
        return False
    try:
        _driver.verify_connectivity()
        return True
    except (ServiceUnavailable, Neo4jError, OSError) as exc:
        logger.warning("CognoDB connectivity check failed: %s", exc)
        return False


@contextmanager
def get_session() -> Iterator[Any]:
    if _driver is None:
        raise DatabaseUnavailableError("Database driver is not initialised.")
    settings = get_settings()
    try:
        session = _driver.session(database=settings.neo4j_database)
    except (ServiceUnavailable, OSError) as exc:
        raise DatabaseUnavailableError(f"Could not reach CognoDB: {exc}") from exc
    try:
        yield session
    except (ServiceUnavailable, OSError) as exc:
        raise DatabaseUnavailableError(f"Lost connection to CognoDB: {exc}") from exc
    except Neo4jError as exc:
        raise DatabaseUnavailableError(f"CognoDB query failed: {exc.message}") from exc
    finally:
        session.close()


def run_query(cypher: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a parameterised Cypher query and return a list of record dicts."""
    with get_session() as session:
        result = session.run(cypher, parameters or {})
        return [record.data() for record in result]


def run_write(cypher: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        result = session.execute_write(lambda tx: list(tx.run(cypher, parameters or {})))
        return [record.data() for record in result]
