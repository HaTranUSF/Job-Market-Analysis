"""Transactional snapshot history in additive market_* PostgreSQL tables."""

import hashlib
import json
import gzip
from pathlib import Path

import pandas as pd
from sqlalchemy import (Boolean, Column, Date, ForeignKeyConstraint, Integer,
                        MetaData, Numeric, String, Table, Text, inspect, select, text)

from ats_sources import ATS_COLUMNS
from pipeline_io import atomic_bytes, collection_identity, utc_now, write_json

metadata = MetaData()
RUNS = Table("market_runs", metadata,
    Column("run_id", String(64), primary_key=True), Column("started_at", Text, nullable=False),
    Column("collection_id", String(64), nullable=False),
    Column("finished_at", Text, nullable=False), Column("status", Text, nullable=False),
    Column("snapshot_sha256", String(64), nullable=False), Column("config_json", Text),
    Column("summary_json", Text), Column("loaded_at", Text, nullable=False))
BOARDS = Table("market_board_runs", metadata,
    Column("run_id", String(64), primary_key=True), Column("board_key", String(64), primary_key=True),
    Column("source", Text, nullable=False), Column("source_board", Text, nullable=False),
    Column("source_region", Text, nullable=False), Column("organization", Text),
    Column("status", Text, nullable=False), Column("collected_at", Text, nullable=False),
    Column("finished_at", Text, nullable=False), Column("raw_postings", Integer),
    Column("matched_postings", Integer), Column("retained_postings", Integer), Column("error", Text),
    ForeignKeyConstraint(["run_id"], ["market_runs.run_id"]))


def column_type(name):
    if name == "is_remote":
        return Boolean()
    if name in {"posted_date", "close_date"}:
        return Date()
    if name.startswith("salary_") and (name.endswith("_usd") or name in {"salary_min", "salary_max"}):
        return Numeric(18, 2)
    return Text()


POSTINGS = Table("market_job_postings", metadata,
    Column("run_id", String(64), primary_key=True), Column("id", String(64), primary_key=True),
    Column("board_key", String(64), nullable=False),
    *[Column(name, column_type(name)) for name in ATS_COLUMNS if name != "id"],
    ForeignKeyConstraint(["run_id", "board_key"], ["market_board_runs.run_id", "market_board_runs.board_key"]))
SKILLS = Table("market_job_skills", metadata,
    Column("run_id", String(64), primary_key=True), Column("job_id", String(64), primary_key=True),
    Column("skill", String(64), primary_key=True),
    ForeignKeyConstraint(["run_id", "job_id"], ["market_job_postings.run_id", "market_job_postings.id"]))

VIEWS = {
    "vw_market_current_jobs": """
        WITH ranked AS (
          SELECT b.*, ROW_NUMBER() OVER (
            PARTITION BY board_key ORDER BY collected_at DESC, run_id DESC) AS rank
          FROM market_board_runs b WHERE status = 'ok'
        ) SELECT p.* FROM market_job_postings p JOIN ranked b
          ON p.run_id = b.run_id AND p.board_key = b.board_key AND b.rank = 1
    """,
    "vw_market_current_skills": """
        SELECT s.* FROM market_job_skills s JOIN vw_market_current_jobs p
        ON s.run_id = p.run_id AND s.job_id = p.id
    """,
    "vw_market_job_history": """
        SELECT id, MIN(collected_at) AS first_seen_at, MAX(collected_at) AS last_seen_at,
          COUNT(*) AS snapshots_seen, COUNT(DISTINCT content_hash) AS versions_seen
        FROM market_job_postings GROUP BY id
    """,
    "vw_market_board_coverage": """
        SELECT r.run_id, r.started_at, r.status AS run_status, b.source,
          COUNT(*) AS boards_attempted,
          SUM(CASE WHEN b.status = 'ok' THEN 1 ELSE 0 END) AS boards_successful,
          SUM(b.raw_postings) AS raw_postings, SUM(b.retained_postings) AS retained_postings
        FROM market_runs r JOIN market_board_runs b ON r.run_id = b.run_id
        GROUP BY r.run_id, r.started_at, r.status, b.source
    """,
}


def ensure_market_schema(engine):
    metadata.create_all(engine)
    repair_collection_history(engine)
    with engine.begin() as conn:
        for name, query in VIEWS.items():
            # CREATE VIEW IF NOT EXISTS is not supported by PostgreSQL.
            if engine.dialect.name == "postgresql":
                conn.execute(text(f"CREATE OR REPLACE VIEW {name} AS {query}"))
            else:
                conn.execute(text(f"CREATE VIEW IF NOT EXISTS {name} AS {query}"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_boards_latest ON market_board_runs (board_key, collected_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_market_posting_history ON market_job_postings (id, collected_at)"))
        if engine.dialect.name == "postgresql":
            conn.execute(text("""CREATE OR REPLACE VIEW vw_market_current_locations AS
                SELECT DISTINCT p.run_id, p.id AS job_id, loc.value ->> 'state' AS state
                FROM vw_market_current_jobs p
                CROSS JOIN LATERAL jsonb_array_elements(CAST(p.locations_json AS jsonb)) AS loc(value)
                WHERE loc.value ->> 'country' = 'US'
                  AND loc.value ->> 'state' IS NOT NULL
            """))


def _remove_runs(conn, run_ids):
    for table in (SKILLS, POSTINGS, BOARDS, RUNS):
        conn.execute(table.delete().where(table.c.run_id.in_(run_ids)))


def _backup_runs(conn, run_ids):
    if not run_ids:
        return
    backup = {table.name: [dict(row) for row in conn.execute(
        select(table).where(table.c.run_id.in_(run_ids))).mappings()]
        for table in (RUNS, BOARDS, POSTINGS, SKILLS)}
    path = Path(__file__).resolve().parents[1] / "data/backups" / (
        "superseded_" + utc_now().replace(":", "").replace("+", "_") + ".json.gz")
    atomic_bytes(path, gzip.compress(json.dumps(backup, default=str).encode("utf-8")))


def repair_collection_history(engine):
    """Migrate collection identities and keep only the latest transformation."""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(72103421)"))
        if "collection_id" not in {c["name"] for c in inspect(conn).get_columns("market_runs")}:
            conn.execute(text("ALTER TABLE market_runs ADD COLUMN collection_id VARCHAR(64)"))
        rows = conn.execute(select(RUNS)).mappings().all()
        configs = {r["run_id"]: json.loads(r["config_json"] or "{}") for r in rows}
        groups = {}
        for row in rows:
            key, seen = row["run_id"], set()
            identity = row["collection_id"]
            while not identity:
                if key in seen:
                    raise ValueError("Circular collection lineage in database")
                seen.add(key)
                config = configs.get(key, {})
                if config.get("collection_id"):
                    identity = config["collection_id"]
                elif config.get("source_run_id"):
                    key = config["source_run_id"]
                else:
                    identity = key
            conn.execute(RUNS.update().where(RUNS.c.run_id == row["run_id"]).values(collection_id=identity))
            groups.setdefault(identity, []).append(row["run_id"])
        superseded = [run_id for group in groups.values() for run_id in sorted(group)[:-1]]
        if superseded:
            _backup_runs(conn, superseded)
            _remove_runs(conn, superseded)
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE market_runs ALTER COLUMN collection_id SET NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_market_runs_collection ON market_runs (collection_id)"))
    return superseded


def _frame_records(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def load_market_run(engine, run_dir, postings, skills, report, manifest, replace_all=False):
    """Keep one processed version per collection; preserve independent collections."""
    if manifest["status"] not in {"complete", "partial"}:
        raise ValueError("Only finalized runs with successful boards can be loaded")
    ensure_market_schema(engine)
    content = b"".join((run_dir / name).read_bytes() for name in (
        "manifest.json", "job_skills.csv", "job_posting_skills.csv", "board_report.json"))
    fingerprint = hashlib.sha256(content).hexdigest()
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(72103421)"))
        if replace_all:
            if postings.empty:
                raise ValueError("Refusing to replace the database with an empty snapshot")
            existing_ids = list(conn.execute(select(RUNS.c.run_id)).scalars())
            _backup_runs(conn, existing_ids)
            _remove_runs(conn, existing_ids)
        old = conn.execute(select(RUNS.c.snapshot_sha256).where(RUNS.c.run_id == manifest["run_id"])).scalar_one_or_none()
        if old is not None:
            if old != fingerprint:
                raise ValueError("This run ID already exists with different data; refusing to overwrite history")
            write_json(run_dir / "database_load.json", dict(verified_at=utc_now(), run_id=manifest["run_id"], snapshot_sha256=fingerprint))
            return False
        identity = collection_identity(manifest, run_dir.parent)
        previous = conn.execute(select(RUNS.c.run_id).where(RUNS.c.collection_id == identity)).scalar_one_or_none()
        if previous:
            if previous > manifest["run_id"]:
                raise ValueError("A newer transformation of this collection is already loaded")
            _backup_runs(conn, [previous])
            _remove_runs(conn, [previous])
        conn.execute(RUNS.insert(), dict(run_id=manifest["run_id"], started_at=manifest["started_at"],
                     collection_id=identity,
                     finished_at=manifest["finished_at"], status=manifest["status"], snapshot_sha256=fingerprint,
                     config_json=json.dumps({k: v for k, v in manifest.items() if k not in {"boards", "summary"}}),
                     summary_json=json.dumps(manifest["summary"]), loaded_at=utc_now()))
        board_columns = {c.name for c in BOARDS.columns}
        board_rows = [{"run_id": manifest["run_id"], **{k: v for k, v in r.items() if k in board_columns}} for r in report]
        if board_rows:
            conn.execute(BOARDS.insert(), board_rows)
        for frame, table in ((postings, POSTINGS), (skills, SKILLS)):
            for start in range(0, len(frame), 500):
                conn.execute(table.insert(), _frame_records(frame.iloc[start:start + 500]))
    write_json(run_dir / "database_load.json", dict(loaded_at=utc_now(), run_id=manifest["run_id"], snapshot_sha256=fingerprint))
    return True
