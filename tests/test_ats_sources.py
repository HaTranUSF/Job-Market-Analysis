import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from ats_sources import (fetch_board, normalize_job, read_directory, select_boards,
                         transform_ats, fetch_ats_jobs)
from unittest.mock import patch


class ATSSourceTests(unittest.TestCase):
    def board(self, provider="lever", **kwargs):
        return dict(provider=provider, slug="Example", name="Example Inc", status="ok", **kwargs)

    def job(self, **kwargs):
        return dict(id="1", text="Data Engineer", categories={"location": "Austin, TX"},
                    descriptionPlain="Python SQL", **kwargs)

    def test_directory_filters_and_preserves_case_and_region(self):
        rows = [self.board(), self.board(), self.board("ashby"),
                dict(provider="greenhouse", slug="closed", status="dead")]
        self.assertEqual(len(select_boards(rows, limit=1)), 2)
        self.assertEqual(select_boards(rows)[0]["slug"], "Example")
        self.assertEqual(select_boards(rows, limit=0), [])

    def test_directory_snapshot_can_be_reused_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companies.jsonl"
            session = Mock()
            session.get.return_value.text = json.dumps(self.board()) + "\n"
            self.assertEqual(len(read_directory(path, session=session)), 1)
            read_directory(path, session=session)
            session.get.assert_called_once()
            self.assertTrue(path.with_suffix(".metadata.json").exists())

    def test_lever_pagination_and_eu_host(self):
        session = Mock()
        session.get.side_effect = [Mock(json=Mock(return_value=[self.job()] * 100)),
                                   Mock(json=Mock(return_value=[self.job()]))]
        jobs = fetch_board(self.board(region="eu"), session)
        self.assertEqual(len(jobs), 101)
        self.assertIn("api.eu.lever.co", session.get.call_args_list[0].args[0])
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["skip"], 100)

    def test_namespaced_ids_and_unknown_dates(self):
        lever = normalize_job(self.job(), self.board(), "today")
        gh = normalize_job(dict(id="1", title="Data Engineer", content="&lt;p&gt;SQL&lt;/p&gt;",
                                updated_at="2026-01-01", location={"name": "Austin, TX"}),
                           self.board("greenhouse"), "today")
        self.assertNotEqual(lever["id"], gh["id"])
        self.assertLessEqual(len(lever["id"]), 64)
        self.assertIsNone(gh["posted_date"])
        self.assertEqual(gh["source_updated_at"], "2026-01-01")
        self.assertEqual(gh["description"], "SQL")

    def test_no_hourly_guessing_or_unknown_remote_country(self):
        record = normalize_job(self.job(salaryRange=dict(min=45, max=60, currency="USD", interval="hour")), self.board(), "today")
        postings, skills = transform_ats([record])
        self.assertEqual(postings.iloc[0].salary_min, 45)
        self.assertEqual(postings.iloc[0].salary_period, "hour")
        self.assertEqual(postings.iloc[0].country, "US")
        self.assertEqual(postings.iloc[0].state, "Texas")
        self.assertIn("python", skills.skill.tolist())
        remote = self.job()
        remote["categories"]["location"] = "Remote"
        record = normalize_job(remote, self.board(), "today")
        self.assertTrue(transform_ats([record])[0].empty)
        self.assertEqual(len(transform_ats([record], True)[0]), 1)
        remote["country"] = "CA"
        record = normalize_job(remote, self.board(), "today")
        self.assertTrue(transform_ats([record], True)[0].empty)

    def test_ashby_salary_and_unlisted_jobs(self):
        job = dict(id="a", title="Data Analyst", location="Remote", isRemote=True,
                   address={"postalAddress": {"addressCountry": "USA"}},
                   compensation={"summaryComponents": [dict(compensationType="Salary", minValue=90000,
                                  maxValue=100000, currencyCode="USD", interval="1 YEAR")]})
        record = normalize_job(job, self.board("ashby"), "today")
        postings, _ = transform_ats([record])
        self.assertEqual(postings.iloc[0].salary_min, 90000)
        self.assertTrue(postings.iloc[0].is_remote)
        job["isListed"] = False
        self.assertIsNone(normalize_job(job, self.board("ashby"), "today"))

    def test_unrelated_engineering_title_excluded(self):
        job = self.job()
        for title in ("Software Engineer", "Sales Engineer - Data & AI Platform", "Technical Account Manager - Data Platform"):
            job["text"] = title
            self.assertIsNone(normalize_job(job, self.board(), "today"))

    def test_failed_board_does_not_abort_other_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "companies.jsonl"
            directory.write_text("\n".join(json.dumps(b) for b in [self.board("greenhouse"), self.board()]))
            report = Path(tmp) / "report.json"
            with patch("ats_sources.fetch_board", side_effect=[requests.HTTPError("404"), [self.job()]]):
                postings, _ = fetch_ats_jobs(directory, report_path=report, delay=0)
            self.assertEqual(len(postings), 1)
            self.assertEqual([r["status"] for r in json.loads(report.read_text())], ["failed", "ok"])


if __name__ == "__main__":
    unittest.main()
