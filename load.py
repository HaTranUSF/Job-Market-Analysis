"""Write transformed postings and skill links to PostgreSQL."""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Integer, Numeric as SQLNumeric

from engine import POSTING_CONTENT_COLUMNS, deduplicate_postings, ensure_postings_schema
from transform import POSTING_COLUMNS

DB_BATCH_SIZE = 1_000
LOG = logging.getLogger("job_market_etl")


def read_database_snapshot(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read all persisted postings and skill links for exports and dashboards."""
    posting_fields = ", ".join(f'"{column}"' for column in POSTING_COLUMNS)
    with engine.connect() as connection:
        postings = pd.read_sql_query(
            text(f'SELECT {posting_fields} FROM "job_skills" ORDER BY "id"'),
            connection,
        )
        skills = pd.read_sql_query(
            text(
                'SELECT "job_id", "skill" FROM "job_posting_skills" '
                'ORDER BY "job_id", "skill"'
            ),
            connection,
        )
    return postings, skills


def load_postings(engine: Engine, postings: pd.DataFrame, skills: pd.DataFrame) -> None:
    """Idempotently replace only IDs in this run, within one database transaction."""
    postings = postings.copy()
    postings["id"] = postings["id"].astype("string").str.strip()
    postings = postings.loc[postings["id"].notna() & postings["id"].ne("")]
    postings = postings.drop_duplicates(subset="id", keep="last").reset_index(drop=True)
    postings = postings.drop_duplicates(
        subset=list(POSTING_CONTENT_COLUMNS),
        keep="last",
    ).reset_index(drop=True)
    if postings.empty:
        raise ValueError("Refusing to load an empty postings dataframe.")

    valid_ids = set(postings["id"].astype(str))
    skills = skills.copy()
    if not skills.empty:
        skills["job_id"] = skills["job_id"].astype("string").str.strip()
        skills = skills.loc[skills["job_id"].isin(valid_ids)]
        skills = skills.drop_duplicates(subset=["job_id", "skill"], keep="last")

    ensure_postings_schema(engine)
    id_column = next(
        column for column in inspect(engine).get_columns("job_skills")
        if column["name"] == "id"
    )
    numeric_id = isinstance(id_column["type"], (Integer, SQLNumeric))
    ids = postings["id"].astype(str).drop_duplicates().tolist()
    if numeric_id:
        if not all(value.isdigit() for value in ids):
            raise ValueError(
                "The existing job_skills.id column is numeric but a posting ID is not."
            )
        ids = [int(value) for value in ids]

    delete_postings = text('DELETE FROM "job_skills" WHERE "id" IN :ids').bindparams(
        bindparam("ids", expanding=True)
    )
    delete_skills = text(
        'DELETE FROM "job_posting_skills" WHERE "job_id" IN :ids'
    ).bindparams(bindparam("ids", expanding=True))

    with engine.begin() as connection:
        for offset in range(0, len(ids), DB_BATCH_SIZE):
            batch_ids = ids[offset : offset + DB_BATCH_SIZE]
            connection.execute(delete_postings, {"ids": batch_ids})
            connection.execute(delete_skills, {"ids": batch_ids})

        load_frame = postings.copy()
        if numeric_id:
            load_frame["id"] = load_frame["id"].astype("int64")
        load_frame.to_sql(
            "job_skills",
            con=connection,
            if_exists="append",
            index=False,
            chunksize=DB_BATCH_SIZE,
            method="multi",
        )
        if not skills.empty:
            skills.to_sql(
                "job_posting_skills",
                con=connection,
                if_exists="append",
                index=False,
                chunksize=DB_BATCH_SIZE,
                method="multi",
            )
            deduplicate_postings(connection)

    LOG.info("Loaded %s postings and %s skill links", len(postings), len(skills))
