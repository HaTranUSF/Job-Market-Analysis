"""Create Gold analytics tables for Power BI and downstream reporting."""

from __future__ import annotations

from pyspark.sql import SparkSession, functions as F


def build_spark_session() -> SparkSession:
    return (
        SparkSession.builder.appName("usajobs-gold")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )


def write_gold_tables(
    spark: SparkSession,
    postings_table_name: str = "silver.job_postings_clean",
    gold_fact_table: str = "gold.fact_job_postings",
    dim_role_table: str = "gold.dim_role",
    dim_location_table: str = "gold.dim_location",
    dim_agency_table: str = "gold.dim_agency",
) -> None:
    """Create fact and dimension tables for BI consumption."""
    spark.sql("CREATE SCHEMA IF NOT EXISTS gold")
    postings = spark.table(postings_table_name)

    fact = postings.select(
        "id",
        "role",
        "title",
        "organization",
        "department",
        "city",
        "state",
        "posted_date",
        "close_date",
        "job_grade",
        "salary_min",
        "salary_max",
        "employment_type",
        "is_remote",
    )
    fact.write.format("delta").mode("overwrite").saveAsTable(gold_fact_table)

    role_dim = postings.select("role").distinct().withColumnRenamed("role", "role_name")
    role_dim.write.format("delta").mode("overwrite").saveAsTable(dim_role_table)

    location_dim = postings.select("city", "state").distinct()
    location_dim.write.format("delta").mode("overwrite").saveAsTable(dim_location_table)

    agency_dim = postings.select("organization").distinct().withColumnRenamed("organization", "agency_name")
    agency_dim.write.format("delta").mode("overwrite").saveAsTable(dim_agency_table)


if __name__ == "__main__":
    spark = build_spark_session()
    try:
        write_gold_tables(spark)
        print("Gold tables created successfully.")
    finally:
        spark.stop()
