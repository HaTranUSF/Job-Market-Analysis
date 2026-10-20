import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError

from ats_sources import normalize_job, transform_ats
from extract.collect_market import board_key, collect_run, new_run, reprocess_run
from transform.market_snapshot import build_snapshot, publish_snapshot
from load.market_store import RUNS, load_market_run, ensure_market_schema
from pipeline_io import read_json, write_json, run_lock


class MarketPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.directory = self.root / "companies.jsonl"
        self.board = dict(provider="lever", slug="Example", status="ok", name="Example Inc")
        self.directory.write_text(json.dumps(self.board), encoding="utf-8")
        self.engine = create_engine("sqlite://")
        @event.listens_for(self.engine, "connect")
        def enable_fks(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def job(self):
        return dict(id="posting1", text="Data Engineer", descriptionPlain="Python and SQL",
                    categories=dict(location="Austin, TX"))

    def snapshot(self, jobs=None, fails=False):
        run = new_run(self.directory, self.root / "runs")
        with patch("extract.collect_market.fetch_board", side_effect=ValueError("bad payload") if fails else None,
                   return_value=[self.job()] if jobs is None else jobs):
            collect_run(run, interval=0)
        return run, build_snapshot(run)

    def test_collection_checkpoints_resume_and_freeze_directory(self):
        run = new_run(self.directory, self.root / "runs")
        with patch("extract.collect_market.fetch_board", return_value=[self.job()]) as fetch:
            collect_run(run, interval=0)
            collect_run(run, interval=0)
            self.assertEqual(fetch.call_count, 1)
        self.directory.write_text("", encoding="utf-8")
        self.assertEqual(len(read_json(run / "manifest.json")["boards"]), 1)
        self.assertTrue((run / "raw" / f"{board_key(self.board)}.json.gz").exists())

    def test_snapshot_history_idempotency_and_zero_jobs(self):
        run1, values1 = self.snapshot()
        self.assertTrue(load_market_run(self.engine, run1, *values1))
        self.assertFalse(load_market_run(self.engine, run1, *values1))
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM vw_market_current_jobs")).scalar(), 1)
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM vw_market_current_skills")).scalar(), 2)
        run2, values2 = self.snapshot(jobs=[])
        load_market_run(self.engine, run2, *values2)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_job_postings")).scalar(), 1)
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM vw_market_current_jobs")).scalar(), 0)
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_runs")).scalar(), 2)

    def test_failed_board_keeps_previous_successful_data(self):
        run1, values1 = self.snapshot()
        load_market_run(self.engine, run1, *values1)
        # A partial run with one failing board and another successful empty board.
        second = dict(provider="ashby", slug="Other", status="ok")
        self.directory.write_text(json.dumps(self.board) + "\n" + json.dumps(second), encoding="utf-8")
        run2 = new_run(self.directory, self.root / "runs")
        with patch("extract.collect_market.fetch_board", side_effect=lambda board, session: [] if board["provider"] == "ashby" else (_ for _ in ()).throw(ValueError("outage"))):
            collect_run(run2, workers=1, interval=0)
        values2 = build_snapshot(run2)
        self.assertEqual(values2[-1]["status"], "partial")
        load_market_run(self.engine, run2, *values2)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM vw_market_current_jobs")).scalar(), 1)

    def test_failed_run_does_not_replace_latest_and_preserves_raw_on_parse_failure(self):
        good, _ = self.snapshot()
        output = self.root / "processed"
        publish_snapshot(good, output)
        bad, values = self.snapshot(jobs=[dict(text="Data Engineer")])
        self.assertEqual(values[-1]["status"], "failed")
        publish_snapshot(bad, output)
        self.assertEqual(read_json(output / "latest.json")["run_id"], good.name)
        self.assertEqual(values[2][0]["status"], "transform_failed")
        self.assertTrue(list((bad / "raw").glob("*.gz")))

    def test_secondary_us_location_and_explicit_annual_salary(self):
        job = dict(id="a", title="Data Analyst", location="Toronto, Canada",
                   address={"postalAddress": {"addressCountry": "CA"}},
                   secondaryLocations=[dict(location="Austin, TX", address={"addressCountry": "US"})],
                   compensation={"summaryComponents": [dict(compensationType="Salary", currencyCode="USD", interval="1 HOUR", minValue=50, maxValue=70)]})
        board = dict(provider="ashby", slug="test")
        postings, _ = transform_ats([normalize_job(job, board, "2026-10-19")])
        self.assertEqual(postings.iloc[0].country, "US")
        self.assertEqual(postings.iloc[0].salary_min, 50)
        self.assertEqual(postings.iloc[0].salary_min_annual_usd, 104000)

    def test_fingerprint_rejects_changed_history(self):
        run, values = self.snapshot()
        load_market_run(self.engine, run, *values)
        with (run / "job_skills.csv").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "different data"):
            load_market_run(self.engine, run, *values)

    def test_failed_load_rolls_back_the_entire_run(self):
        run, values = self.snapshot()
        postings, skills, report, manifest = values
        invalid = skills.copy()
        invalid.loc[0, "job_id"] = "missing-posting"
        with self.assertRaises(IntegrityError):
            load_market_run(self.engine, run, postings, invalid, report, manifest)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(RUNS.c.run_id)).all(), [])
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_job_postings")).scalar(), 0)

    def test_run_lock_prevents_concurrent_writers_and_releases(self):
        with run_lock(self.root):
            with self.assertRaisesRegex(RuntimeError, "Another process"):
                with run_lock(self.root):
                    pass
        with run_lock(self.root):
            pass

    def test_numeric_hash_is_stable_across_salary_nulls_in_other_jobs(self):
        job = self.job()
        job["salaryRange"] = dict(min=100000, max=150000, currency="USD", interval="per-year-salary")
        record = normalize_job(job, self.board, "2026-10-19")
        first, _ = transform_ats([record])
        other_job = self.job()
        other_job["id"] = "posting2"
        other = normalize_job(other_job, self.board, "2026-10-20")
        second, _ = transform_ats([record, other])
        self.assertEqual(first.iloc[0].content_hash, second.iloc[0].content_hash)

    def test_invalid_pay_and_mixed_date_formats(self):
        first_job = self.job()
        first_job["salaryRange"] = dict(min=150000, max=100000, currency="USD", interval="year")
        first = normalize_job(first_job, self.board, "2026-10-19")
        first["posted_date"] = "2026-10-19"
        second_job = self.job()
        second_job["id"] = "posting2"
        second = normalize_job(second_job, self.board, "2026-10-19")
        second["posted_date"] = "2026-10-18T12:00:00.123Z"
        postings, _ = transform_ats([first, second])
        self.assertTrue(postings.iloc[0][["salary_min", "salary_max"]].isna().all())
        self.assertFalse(postings.posted_date.isna().any())

    def test_lever_secondary_country_and_greenhouse_prospect(self):
        job = self.job()
        job["country"] = "CA"
        job["categories"] = dict(location="Toronto, Canada", allLocations=["Toronto, Canada", "Austin, TX"])
        postings, _ = transform_ats([normalize_job(job, self.board, "2026-10-19")])
        self.assertEqual(postings.iloc[0].country, "US")
        self.assertIsNone(normalize_job(dict(id=1, title="Data Engineer", internal_job_id=None),
                                       dict(provider="greenhouse", slug="test"), "2026-10-19"))

    def test_reprocess_preserves_source_and_uses_no_network(self):
        original, values = self.snapshot()
        original_manifest = (original / "manifest.json").read_bytes()
        with patch("extract.collect_market.fetch_board", side_effect=AssertionError("No network expected")):
            derived = reprocess_run(original, self.root / "runs")
            postings, _, _, manifest = build_snapshot(derived)
        self.assertNotEqual(derived.name, original.name)
        self.assertEqual(manifest["source_run_id"], original.name)
        self.assertEqual(postings.iloc[0].id, values[0].iloc[0].id)
        self.assertEqual(postings.iloc[0].collected_at, values[0].iloc[0].collected_at)
        self.assertEqual(original_manifest, (original / "manifest.json").read_bytes())
        self.assertEqual(len(manifest["transform_sha256"]), 64)

    def test_dc_city_is_not_mistaken_for_washington_state(self):
        job = self.job()
        job["categories"]["location"] = "Washington, District of Columbia, United States"
        postings, _ = transform_ats([normalize_job(job, self.board, "2026-10-19")])
        self.assertEqual(postings.iloc[0].city, "Washington")
        self.assertEqual(postings.iloc[0].state, "District of Columbia")

    def test_replace_all_removes_other_collections_without_duplicates(self):
        original, values = self.snapshot()
        load_market_run(self.engine, original, *values)
        newer, updated = self.snapshot()
        load_market_run(self.engine, newer, *updated, replace_all=True)
        load_market_run(self.engine, newer, *updated, replace_all=True)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(RUNS.c.run_id)).all(), [(newer.name,)])
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_job_postings")).scalar(), 1)

    def test_failed_replace_all_preserves_existing_data(self):
        original, values = self.snapshot()
        load_market_run(self.engine, original, *values)
        newer, (postings, skills, report, manifest) = self.snapshot()
        skills.loc[0, "job_id"] = "missing"
        with self.assertRaises(IntegrityError):
            load_market_run(self.engine, newer, postings, skills, report, manifest, replace_all=True)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(RUNS.c.run_id)).scalar(), original.name)

    def test_reprocessed_collection_replaces_history_and_blocks_older_reload(self):
        original, values = self.snapshot()
        load_market_run(self.engine, original, *values)
        derived = reprocess_run(original, self.root / "runs")
        updated = build_snapshot(derived)
        load_market_run(self.engine, derived, *updated)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_runs")).scalar(), 1)
            self.assertEqual(conn.execute(text("SELECT COUNT(*) FROM market_job_postings")).scalar(), 1)
            self.assertEqual(conn.execute(text("SELECT snapshots_seen FROM vw_market_job_history")).scalar(), 1)
        with self.assertRaisesRegex(ValueError, "newer transformation"):
            load_market_run(self.engine, original, *values)

    def test_failed_reprocessing_load_keeps_previous_collection(self):
        original, values = self.snapshot()
        load_market_run(self.engine, original, *values)
        derived = reprocess_run(original, self.root / "runs")
        postings, skills, report, manifest = build_snapshot(derived)
        skills.loc[0, "job_id"] = "invalid-job"
        with self.assertRaises(IntegrityError):
            load_market_run(self.engine, derived, postings, skills, report, manifest)
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(select(RUNS.c.run_id)).scalar(), original.name)

    def test_legacy_duplicate_collection_migration(self):
        with self.engine.begin() as conn:
            conn.execute(text('CREATE TABLE market_runs (run_id VARCHAR(64) PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, status TEXT NOT NULL, snapshot_sha256 VARCHAR(64) NOT NULL, config_json TEXT, summary_json TEXT, loaded_at TEXT NOT NULL)'))
            for run_id, source in (("v1", "original"), ("v2", "v1")):
                conn.execute(text('INSERT INTO market_runs VALUES (:id, :stamp, :stamp, :status, :hash, :config, :summary, :stamp)'),
                             dict(id=run_id, stamp="2026-10-19", status="complete", hash="fingerprint",
                                  config=json.dumps(dict(source_run_id=source)), summary="{}"))
        ensure_market_schema(self.engine)
        with self.engine.connect() as conn:
            rows = conn.execute(select(RUNS.c.run_id, RUNS.c.collection_id)).all()
            self.assertEqual(rows, [("v2", "original")])

    def test_readable_overview_has_one_line_per_job_and_combined_skills(self):
        run, _ = self.snapshot()
        output = self.root / "processed"
        publish_snapshot(run, output)
        import pandas as pd
        overview = pd.read_csv(output / "jobs_overview.csv")
        self.assertEqual(len(overview), 1)
        self.assertEqual(overview.iloc[0].skills, "python, sql")
        self.assertNotIn("description", overview.columns)
        self.assertEqual(len((output / "jobs_overview.csv").read_text(encoding="utf-8-sig").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
