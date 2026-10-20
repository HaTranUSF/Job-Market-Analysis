"""Reconcile a saved snapshot with its manifest and optional PostgreSQL load."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

from database import create_db_engine
from transform.market_snapshot import read_snapshot
from pipeline_io import read_json


def verify_snapshot(run_dir, database=False):
    run_dir = Path(run_dir)
    postings, skills, report, manifest = read_snapshot(run_dir)
    summary = manifest["summary"]
    checks = {
        "posting_count": len(postings) == summary["retained_postings"],
        "skill_count": len(skills) == summary["skill_links"],
        "board_count": len(report) == summary["boards_attempted"],
        "unique_postings": not postings.id.duplicated().any(),
        "unique_skills": not skills.duplicated(["job_id", "skill"]).any(),
        "no_orphan_skills": set(skills.job_id).issubset(set(postings.id)),
        "run_ids_match": postings.run_id.eq(manifest["run_id"]).all() and skills.run_id.eq(manifest["run_id"]).all(),
        "directory_fingerprint": hashlib.sha256((run_dir / "directory.jsonl").read_bytes()).hexdigest() == manifest["directory_sha256"],
    }
    if not manifest["include_unknown_country"]:
        checks["us_scope"] = postings.country.eq("US").all()
    locations_path = Path(__file__).parent / "data/processed/job_locations.csv"
    latest_path = Path(__file__).parent / "data/processed/latest.json"
    is_latest = latest_path.exists() and read_json(latest_path)["run_id"] == manifest["run_id"]
    locations = pd.read_csv(locations_path) if is_latest and locations_path.exists() else None
    if locations is not None:
        checks["unique_job_states"] = not locations.duplicated(["run_id", "job_id", "state"]).any()
        checks["no_orphan_locations"] = set(locations.job_id).issubset(set(postings.id))
    db_counts = {}
    if database:
        load_dotenv(Path(__file__).parent / ".env")
        engine = create_db_engine()
        try:
            with engine.connect() as conn:
                for table, expected in (("market_runs", 1), ("market_board_runs", len(report)),
                                        ("market_job_postings", len(postings)), ("market_job_skills", len(skills))):
                    count = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE run_id = :run_id"),
                                         {"run_id": manifest["run_id"]}).scalar_one()
                    db_counts[table] = count
                    checks[table] = count == expected
                if locations is not None:
                    count = conn.execute(text("SELECT COUNT(*) FROM vw_market_current_locations WHERE run_id = :run_id"),
                                         {"run_id": manifest["run_id"]}).scalar_one()
                    checks["current_location_count"] = count == len(locations)
        finally:
            engine.dispose()
    result = dict(run_id=manifest["run_id"], status=manifest["status"],
                  postings=len(postings), skill_links=len(skills),
                  checks={key: bool(value) for key, value in checks.items()}, database_rows=db_counts)
    if not all(checks.values()):
        raise ValueError(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir or Path(read_json(Path(__file__).parent / "data/processed/latest.json")["run_dir"])
    print(json.dumps(verify_snapshot(run_dir, args.database), indent=2))
