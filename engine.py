"""PostgreSQL engine configuration and target table schema."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Engine, URL

metadata = MetaData()
POSTINGS_TABLE = Table(
    "job_skills",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("role", String(128)),
    Column("title", Text),
    Column("organization", Text),
    Column("department", Text),
    Column("city", Text),
    Column("state", Text),
    Column("description", Text),
    Column("posted_date", Date),
    Column("close_date", Date),
    Column("job_grade", String(64)),
    Column("salary_min", Numeric(14, 2)),
    Column("salary_max", Numeric(14, 2)),
    Column("employment_type", String(64)),
    Column("is_remote", Boolean),
)
POSTING_SKILLS_TABLE = Table(
    "job_posting_skills",
    metadata,
    Column("job_id", String(64), primary_key=True),
    Column("skill", String(64), primary_key=True),
)
POSTING_CONTENT_COLUMNS = tuple(
    column.name for column in POSTINGS_TABLE.columns if column.name != "id"
)


def deduplicate_postings(connection: Any) -> None:
    """Keep one posting per exact content match, ignoring the source ID."""
    content_fields = ", ".join(f'"{column}"' for column in POSTING_CONTENT_COLUMNS)
    connection.execute(
        text(
            'WITH ranked AS ('
            f'SELECT "id", FIRST_VALUE("id") OVER (PARTITION BY {content_fields} '
            'ORDER BY "id") AS canonical_id, '
            f'ROW_NUMBER() OVER (PARTITION BY {content_fields} ORDER BY "id") '
            'AS duplicate_rank FROM "job_skills" WHERE "id" IS NOT NULL'
            '), duplicates AS ('
            'SELECT "id", canonical_id FROM ranked WHERE duplicate_rank > 1'
            ') INSERT INTO "job_posting_skills" ("job_id", "skill") '
            'SELECT duplicates.canonical_id, skills."skill" '
            'FROM duplicates JOIN "job_posting_skills" skills '
            'ON skills."job_id" = duplicates."id" '
            'ON CONFLICT DO NOTHING'
        )
    )
    connection.execute(
        text(
            'DELETE FROM "job_skills" WHERE "id" IN ('
            'SELECT "id" FROM ('
            f'SELECT "id", ROW_NUMBER() OVER (PARTITION BY {content_fields} '
            'ORDER BY "id") AS duplicate_rank FROM "job_skills" '
            'WHERE "id" IS NOT NULL'
            ') ranked WHERE duplicate_rank > 1)'
        )
    )
    connection.execute(
        text(
            'DELETE FROM "job_posting_skills" WHERE ctid IN ('
            'SELECT row_id FROM ('
            'SELECT ctid AS row_id, ROW_NUMBER() OVER ('
            'PARTITION BY "job_id", "skill" ORDER BY ctid'
            ') AS duplicate_rank FROM "job_posting_skills"'
            ') ranked WHERE duplicate_rank > 1)'
        )
    )
    connection.execute(
        text(
            'DELETE FROM "job_posting_skills" s WHERE NOT EXISTS ('
            'SELECT 1 FROM "job_skills" j WHERE j."id" = s."job_id")'
        )
    )


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


def ensure_postings_schema(engine: Engine) -> None:
    """Create target tables, deduplicate legacy data, and enforce unique job keys."""
    metadata.create_all(engine)
    existing = {column["name"] for column in inspect(engine).get_columns("job_skills")}
    with engine.begin() as connection:
        for column in POSTINGS_TABLE.columns:
            if column.name not in existing:
                sql_type = column.type.compile(dialect=engine.dialect)
                connection.execute(
                    text(f'ALTER TABLE "job_skills" ADD COLUMN "{column.name}" {sql_type}')
                )
        # Keep the most recently posted record for a duplicated USAJOBS ID.
        # ctid provides a deterministic tie-breaker when dates are equal or missing.
        connection.execute(text('DELETE FROM "job_skills" WHERE "id" IS NULL'))
        connection.execute(
            text(
                'DELETE FROM "job_skills" WHERE ctid IN ('
                'SELECT row_id FROM ('
                'SELECT ctid AS row_id, ROW_NUMBER() OVER ('
                'PARTITION BY "id" ORDER BY "posted_date" DESC NULLS LAST, ctid DESC'
                ') AS duplicate_rank FROM "job_skills"'
                ') ranked WHERE duplicate_rank > 1)'
            )
        )
        deduplicate_postings(connection)
        connection.execute(text('ALTER TABLE "job_skills" ALTER COLUMN "id" SET NOT NULL'))
        connection.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS "uq_job_skills_id" '
                'ON "job_skills" ("id")'
            )
        )
        connection.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS "uq_job_posting_skills_pair" '
                'ON "job_posting_skills" ("job_id", "skill")'
            )
        )
