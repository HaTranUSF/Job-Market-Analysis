"""Run the full Databricks medallion pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bronze_ingest import build_spark_session as build_bronze_session
from bronze_ingest import write_bronze_table
from gold_analytics import write_gold_tables
from silver_transform import write_silver_tables


def main() -> None:
    spark = build_bronze_session()
    try:
        write_bronze_table(spark)
        write_silver_tables(spark)
        write_gold_tables(spark)
        print("USAJOBS medallion pipeline completed successfully.")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
