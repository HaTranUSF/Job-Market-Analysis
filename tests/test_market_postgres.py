"""Opt-in integration tests in disposable, uniquely named PostgreSQL schemas."""

import os
import uuid
import unittest

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from database import create_db_engine
import test_market_pipeline


@unittest.skipUnless(os.getenv("TEST_POSTGRES") == "1", "Set TEST_POSTGRES=1 for isolated PostgreSQL integration tests")
class PostgreSQLMarketPipelineTests(test_market_pipeline.MarketPipelineTests):
    def setUp(self):
        super().setUp()
        self.engine.dispose()
        load_dotenv()
        self.admin_engine = create_db_engine()
        self.schema = "etl_test_" + uuid.uuid4().hex
        with self.admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(self.admin_engine.url, connect_args={"options": f"-csearch_path={self.schema}"})

    def tearDown(self):
        super().tearDown()
        with self.admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin_engine.dispose()
