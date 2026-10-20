"""Collect company job boards, retain snapshots, and load PostgreSQL history."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from database import create_db_engine
from ats_sources import PROVIDERS
from extract.collect_market import collect_run, new_run, reprocess_run
from transform.market_snapshot import build_snapshot, publish_snapshot
from load.market_store import load_market_run

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("job_market_etl")


def run_pipeline(
    output_dir: Path,
    skip_load: bool = True,
    no_csv: bool = False,
    providers=PROVIDERS,
    directory_path: Path = ROOT / "data" / "directory" / "companies.jsonl",
    board_limit: int | None = None,
    refresh_directory: bool = False,
    include_unknown_country: bool = False,
    runs_dir: Path = ROOT / "data" / "runs",
    resume: Path | None = None,
    workers: int = 4,
    active_only: bool = False,
    retry_failed: bool = False,
    reprocess: Path | None = None,
    replace_all: bool = False,
) -> tuple[int, int]:
    """Collect every board, retain dated snapshots, and optionally load PostgreSQL."""
    load_dotenv(ROOT / ".env", override=False)
    run_dir = resume or (reprocess_run(reprocess, runs_dir) if reprocess else new_run(
        directory_path, runs_dir, providers, board_limit,
        refresh_directory, active_only, include_unknown_country))
    LOG.info("Snapshot directory: %s", run_dir)
    from pipeline_io import run_lock
    with run_lock(run_dir):
        if not reprocess:
            collect_run(run_dir, workers, retry_failed)
        postings, skills, report, manifest = build_snapshot(run_dir)
        LOG.info("Run %s: %s", manifest["run_id"], manifest["summary"])
        if manifest["status"] == "failed":
            raise RuntimeError(f"All boards failed; latest exports preserved. See {run_dir / 'board_report.json'}")
        if not no_csv:
            publish_snapshot(run_dir, output_dir)
        if not skip_load:
            engine = create_db_engine()
            try:
                load_market_run(engine, run_dir, postings, skills, report, manifest, replace_all=replace_all)
            finally:
                engine.dispose()
    return len(postings), len(skills)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=list(PROVIDERS))
    parser.add_argument("--directory-path", type=Path, default=ROOT / "data/directory/companies.jsonl")
    parser.add_argument("--refresh-directory", action="store_true")
    parser.add_argument("--board-limit", type=int, default=0, help="Boards per provider (default: 0 = all).")
    parser.add_argument("--workers", type=int, default=4, help="Parallel board requests (1-16; default: 4).")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "data/runs")
    saved = parser.add_mutually_exclusive_group()
    saved.add_argument("--resume", type=Path, help="Resume or load a saved run directory; uses its frozen settings.")
    saved.add_argument("--reprocess", type=Path, help="Create a new snapshot from saved raw responses without fetching boards.")
    parser.add_argument("--active-boards-only", action="store_true", help="Skip directory boards marked dead or unconfirmed.")
    parser.add_argument("--retry-failed", action="store_true", help="Retry failed boards in an interrupted, unfinished run.")
    parser.add_argument("--include-unknown-country", action="store_true", help="Also retain jobs with unknown country; does not imply US eligibility.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "processed",
        help="Directory for atomic CSV outputs (default: data/processed).",
    )
    loading = parser.add_mutually_exclusive_group()
    loading.add_argument("--load", action="store_true", help="Load snapshot history into PostgreSQL market_* tables.")
    parser.add_argument("--replace-market-data", action="store_true", help="With --load, back up and replace all company-market snapshots in one transaction.")
    loading.add_argument(
        "--skip-load",
        action="store_true",
        help="Collect without PostgreSQL (the default).",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Do not publish latest CSV copies (dated ATS run artifacts are always retained).",
    )
    args = parser.parse_args()
    if args.board_limit < 0:
        parser.error("--board-limit must be zero or positive")
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    if (args.resume or args.reprocess) and args.refresh_directory:
        parser.error("Saved runs cannot refresh their frozen directory")
    if args.retry_failed and not args.resume:
        parser.error("--retry-failed requires --resume")
    if args.replace_market_data and not args.load:
        parser.error("--replace-market-data requires --load")
    return args


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()
    try:
        job_count, skill_count = run_pipeline(
            args.output_dir,
            skip_load=not args.load,
            no_csv=args.no_csv,
            providers=args.providers,
            directory_path=args.directory_path, board_limit=args.board_limit or None,
            refresh_directory=args.refresh_directory,
            include_unknown_country=args.include_unknown_country,
            runs_dir=args.runs_dir, resume=args.resume, workers=args.workers,
            active_only=args.active_boards_only, retry_failed=args.retry_failed,
            reprocess=args.reprocess,
            replace_all=args.replace_market_data,
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
