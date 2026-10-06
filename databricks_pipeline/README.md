# Databricks Medallion Setup

This folder contains a Databricks-ready medallion architecture for the USAJOBS job market project.

## Layers

- Bronze: raw USAJOBS API responses
- Silver: cleaned and normalized job postings and skill links
- Gold: analytics tables for dashboards and Power BI

## Files

- `bronze_ingest.py` - writes raw JSON payloads to the Bronze Delta table
- `silver_transform.py` - reuses the existing transformation logic and writes Silver tables
- `gold_analytics.py` - creates aggregated analytics tables for reporting
- `run_pipeline.py` - orchestrates the full flow

## Local development

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your USAJOBS credentials.
3. Run the pipeline:
   ```bash
   python databricks_pipeline/run_pipeline.py
   ```

## Databricks deployment

Upload these scripts to a Databricks workspace and run them as notebook tasks or workflow jobs.

Recommended order:
1. `bronze_ingest`
2. `silver_transform`
3. `gold_analytics`

Use the following table names:

- `bronze.usajobs_raw`
- `silver.job_postings_clean`
- `silver.job_posting_skills`
- `gold.fact_job_postings`
- `gold.dim_role`
- `gold.dim_location`
- `gold.dim_agency`

## Power BI

Connect Power BI to the Gold layer and build reports from the fact and dimension tables instead of working directly from raw records.
