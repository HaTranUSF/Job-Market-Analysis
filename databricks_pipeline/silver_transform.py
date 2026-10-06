"""Read Bronze raw JSON, transform it, and write Silver Delta tables."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pyspark.sql import SparkSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from transform import transform_jobs


def build_spark_session() -> SparkSession:
    return (
        SparkSession.builder.appName("usajobs-silver")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )


def bronze_to_dataframe(spark: SparkSession, bronze_table_name: str = "bronze.usajobs_raw") -> pd.DataFrame:
    """Read Bronze JSON rows and convert them into a pandas DataFrame for transformation."""
    bronze_df = spark.table(bronze_table_name).select("payload_json")
    rows = bronze_df.toPandas().to_dict(orient="records")
    records = []
    for row in rows:
        raw = row.get("payload_json")
        if raw is None:
            continue
        records.append(json.loads(raw))
    return pd.DataFrame(records)


def write_silver_tables(
    spark: SparkSession,
    bronze_table_name: str = "bronze.usajobs_raw",
    postings_table_name: str = "silver.job_postings_clean",
    skills_table_name: str = "silver.job_posting_skills",
) -> None:
    """Transform Bronze records into Silver tables for job postings and skill links."""
    load_dotenv()
    raw = bronze_to_dataframe(spark, bronze_table_name)
    if raw.empty:
        raise ValueError("No Bronze data found. Run the Bronze ingestion step first.")

    postings, skills = transform_jobs(raw)

    spark.sql("CREATE SCHEMA IF NOT EXISTS silver")
    spark.createDataFrame(postings).write.format("delta").mode("overwrite").saveAsTable(postings_table_name)
    spark.createDataFrame(skills).write.format("delta").mode("overwrite").saveAsTable(skills_table_name)


if __name__ == "__main__":
    spark = build_spark_session()
    try:
        write_silver_tables(spark)
        print("Silver Delta tables created successfully.")
    finally:
        spark.stop()
