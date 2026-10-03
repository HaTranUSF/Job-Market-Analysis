import unittest

import pandas as pd

from etl_job_market import transform_jobs


class TransformJobsTests(unittest.TestCase):
    def test_normalizes_postings_and_extracts_skills(self):
        raw = pd.DataFrame(
            [
                {
                    "id": "1001",
                    "role": "data engineer",
                    "title": "Senior Data Engineer",
                    "location": "San Francisco, California",
                    "organization": "Example Agency",
                    "department": "Technology",
                    "description": "Python, SQL, AWS, Power BI, and machine learning.",
                    "posted_date": "2026-06-11T11:49:11.8070",
                    "close_date": "2026-06-22T23:59:59.9970",
                    "job_grade": [{"Code": "GS"}],
                    "salary_min": "45",
                    "salary_max": "60",
                    "employment_type": "1",
                    "is_remote": "true",
                },
                {
                    "id": "1002",
                    "role": "machine learning engineer",
                    "title": "Machine Learning Engineer",
                    "location": "Multiple Locations",
                    "organization": "Example Agency",
                    "department": "Research",
                    "description": "Data analysis and reporting with R.",
                    "posted_date": "2026-06-12",
                    "close_date": None,
                    "job_grade": "GG",
                    "salary_min": 120000,
                    "salary_max": 150000,
                    "employment_type": {"Code": "2"},
                    "is_remote": False,
                },
                {
                    "id": "1003",
                    "role": "data analyst",
                    "title": "Automotive Data Analyst",
                    "location": "Austin, Texas",
                    "organization": "Example Agency",
                    "department": "Operations",
                    "description": "Excel and SQL",
                    "posted_date": "2026-06-12",
                    "close_date": "2026-06-30",
                    "job_grade": None,
                    "salary_min": None,
                    "salary_max": None,
                    "employment_type": "1",
                    "is_remote": False,
                },
                {
                    "id": "1004",
                    "role": "data analyst",
                    "title": "Data Analyst",
                    "location": "Toronto, Ontario",
                    "organization": "Example Agency",
                    "department": "Analysis",
                    "description": "SQL",
                    "posted_date": "2026-06-12",
                    "close_date": "2026-06-30",
                    "job_grade": "GS",
                    "salary_min": 100000,
                    "salary_max": 120000,
                    "employment_type": "1",
                    "is_remote": False,
                },
            ]
        )

        postings, skills = transform_jobs(raw)

        self.assertEqual(postings["id"].tolist(), ["1001", "1002"])
        first = postings.iloc[0]
        self.assertEqual(first["role"], "data engineer")
        self.assertEqual(first["salary_min"], 45 * 2080)
        self.assertEqual(first["job_grade"], "GS")
        self.assertEqual(first["employment_type"], "Full-Time")
        self.assertTrue(first["is_remote"])
        self.assertEqual(first["posted_date"], pd.Timestamp("2026-06-11").date())

        second = postings.iloc[1]
        self.assertEqual(second["city"], "Various Cities")
        self.assertEqual(second["state"], "Multiple Locations")
        self.assertEqual(second["employment_type"], "Part-Time")

        skill_pairs = set(map(tuple, skills.itertuples(index=False, name=None)))
        self.assertIn(("1001", "python"), skill_pairs)
        self.assertIn(("1001", "power bi"), skill_pairs)
        self.assertIn(("1001", "machine learning"), skill_pairs)
        self.assertIn(("1002", "data analysis"), skill_pairs)
        self.assertNotIn(("1003", "sql"), skill_pairs)


if __name__ == "__main__":
    unittest.main()
