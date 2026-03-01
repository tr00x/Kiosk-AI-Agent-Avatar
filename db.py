"""db.py — MySQL connection module for Open Dental database.

Features:
- Connection pooling (reuse connections across queries)
- Retry with exponential backoff on connection failures
"""

import os
import time
from contextlib import contextmanager

import mysql.connector
from mysql.connector import Error, pooling
from loguru import logger

# ---------------------------------------------------------------------------
# Connection pool (initialized lazily on first use)
# ---------------------------------------------------------------------------
_pool = None
_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]  # seconds between retries


def _get_pool():
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        try:
            _pool = pooling.MySQLConnectionPool(
                pool_name="opendental_pool",
                pool_size=5,
                pool_reset_session=True,
                host=os.environ["DB_HOST"],
                port=int(os.environ.get("DB_PORT", "3306")),
                user=os.environ["DB_USER"],
                password=os.environ.get("DB_PASSWORD", ""),
                database=os.environ["DB_NAME"],
                connect_timeout=10,
                charset="utf8",
                use_unicode=True,
            )
            logger.info("MySQL connection pool created (size=5)")
        except KeyError as exc:
            raise RuntimeError(f"Missing required environment variable: {exc}") from exc
        except Error as exc:
            raise RuntimeError(f"Failed to create MySQL pool: {exc}") from exc
    return _pool


@contextmanager
def get_connection():
    """Get a pooled MySQL connection with retry logic.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s).
    """
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            pool = _get_pool()
            conn = pool.get_connection()
            break
        except (Error, RuntimeError) as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[attempt]
                logger.warning(f"DB connection attempt {attempt + 1}/{_MAX_RETRIES} failed: {exc}. Retrying in {delay}s...")
                time.sleep(delay)
                # Reset pool on failure so next attempt creates fresh connections
                global _pool
                _pool = None
            else:
                raise RuntimeError(f"Failed to connect to MySQL after {_MAX_RETRIES} attempts: {last_error}") from last_error
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def rows_to_dicts(cursor) -> list[dict]:
    """Convert cursor results to a list of dicts."""
    if cursor.description is None:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
