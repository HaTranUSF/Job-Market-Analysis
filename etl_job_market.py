"""Run the USAJOBS extract-transform-load pipeline."""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy.engine import Engine

from engine import create_db_engine
from extract import fetch_jobs
from load import load_postings, read_database_snapshot
from transform import transform_jobs

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("job_market_etl")


def _atomic_csv_write(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            frame.to_csv(temp_file, index=False)
        os.replace(temp_path, destination)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def write_csv_outputs(
    postings: pd.DataFrame,
    skills: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Write clean postings and job-skill links as atomic CSV snapshots."""
    _atomic_csv_write(postings, output_dir / "job_skills.csv")
    _atomic_csv_write(skills, output_dir / "job_posting_skills.csv")
    LOG.info("Wrote CSV outputs to %s", output_dir)


def run_pipeline(
    output_dir: Path,
    skip_load: bool = False,
    no_csv: bool = False,
) -> tuple[int, int]:
    """Extract and transform jobs, load PostgreSQL, and export the database snapshot."""
    load_dotenv(ROOT / ".env", override=False)
    raw = fetch_jobs(
        os.getenv("USAJOBS_USER_AGENT", ""),
        os.getenv("USAJOBS_AUTH_KEY", ""),
    )
    postings, skills = transform_jobs(raw)
    if postings.empty:
        raise RuntimeError(
            "No US data-role postings remain after transformation; refusing to load."
        )

    if skip_load:
        if not no_csv:
            write_csv_outputs(postings, skills, output_dir)
        return len(postings), len(skills)

    engine: Engine = create_db_engine()
    try:
        load_postings(engine, postings, skills)
        database_postings, database_skills = read_database_snapshot(engine)
        if not no_csv:
            write_csv_outputs(database_postings, database_skills, output_dir)
        return len(database_postings), len(database_skills)
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "processed",
        help="Directory for atomic CSV outputs (default: data/processed).",
    )
    parser.add_argument(
        "--skip-load",
        action="store_true",
        help="Only extract and write CSV files; do not connect to PostgreSQL.",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Do not write CSV outputs.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()
    try:
        job_count, skill_count = run_pipeline(
            args.output_dir,
            skip_load=args.skip_load,
            no_csv=args.no_csv,
        )
    except Exception:
        LOG.exception("ETL failed")
        return 1
    LOG.info(
        "ETL completed successfully: %s postings, %s skill links",
        job_count,
        skill_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
