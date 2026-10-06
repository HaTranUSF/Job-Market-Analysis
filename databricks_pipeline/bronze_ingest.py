"""Write raw USAJOBS payloads into the Bronze Delta layer."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pyspark.sql import SparkSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extract import fetch_jobs


def build_spark_session() -> SparkSession:
    """Create a Spark session configured for Delta tables."""
    return (
        SparkSession.builder.appName("usajobs-bronze")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )


def write_bronze_table(
    spark: SparkSession,
    bronze_table_name: str = "bronze.usajobs_raw",
    user_agent: str | None = None,
    auth_key: str | None = None,
) -> None:
    """Fetch raw USAJOBS job records and append them as JSON payloads to the Bronze table."""
    load_dotenv()
    user_agent = user_agent or os.getenv("USAJOBS_USER_AGENT")
    auth_key = auth_key or os.getenv("USAJOBS_AUTH_KEY")

    raw = fetch_jobs(user_agent or "", auth_key or "")
    rows = []
    for _, record in raw.iterrows():
        rows.append(
            {
                "job_id": str(record["id"]),
                "source": "usajobs",
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "payload_json": json.dumps(record.to_dict(), default=str),
            }
        )

    spark.sql("CREATE SCHEMA IF NOT EXISTS bronze")
    df = spark.createDataFrame(rows)
    df.write.format("delta").mode("append").saveAsTable(bronze_table_name)


if __name__ == "__main__":
    spark = build_spark_session()
    try:
        write_bronze_table(spark)
        print("Bronze Delta table created successfully.")
    finally:
        spark.stop()
