"""PostgreSQL connection settings for company job-market history."""

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL


def create_db_engine() -> Engine:
    """Create a PostgreSQL connection from DB_* environment settings."""
    required = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Missing database settings in environment/.env: {', '.join(missing)}"
        )

    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1_800)
