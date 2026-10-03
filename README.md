# 📊 Data Job Market Analysis & Cloud Data Pipeline

An end-to-end data engineering and analytics project that builds an automated ETL/ELT pipeline to extract, transform, and analyze over 12,000 global tech job postings. Features automated unstructured-to-structured processing via Python, a centralized data warehouse in Snowflake, and interactive business intelligence dashboarding.

## 🔗 Project Links
- **✨ Live Web Portfolio View:** [Explore the Interactive Specification Site](index.html)
- **📁 Core Repository Source:** [GitHub Source File Index](https://github.com/HaTranUSF/Data-Job-Market-Analysis)

---

## 📋 Project Overview (STAR Breakdown)

### 🔹 Situation
Navigating the rapidly evolving data career landscape requires clear visibility into market trends, salary distributions, and tooling prerequisites. With thousands of scattered, unstructured job postings updated daily, manually assessing which skills (e.g., Python, SQL, AWS) maximize career ROI is highly inefficient. 

### 🔹 Task
Design and execute a scalable cloud architecture capable of ingestion, normalization, schema modeling, and downstream semantic reporting for over 12,000 industry job listings. The project goals were twofold: extract actionable labor market insights and showcase advanced data pipeline capabilities.

### 🔹 Action
Systematically engineered an ELT/ETL framework split across three distinct tiers:
1. **API Ingestion & Schema Mapping:** Programmatically targeted data sources via Python APIs, translating noisy, unstructured JSON metadata blocks into clean tabular staging environments.
2. **Cloud Data Warehousing (Snowflake & Snowpark):** Managed database connectivity via the Snowflake Connector and `snowflake-sqlalchemy`. Created a scalable target data schema utilizing optimized Python routines (`write_pandas`) to securely stream bulk rows directly into Snowflake data tables (`JOB_POSTINGS`, `JOB_SKILLS`).
3. **Data Cleansing & Feature Engineering:** Developed an algorithmic data sanitization workflow in Jupyter notebooks (`Pipeline_for_Data_Job_Market_Analysis.ipynb`). Engineered one-hot-encoded token matrices for high-demand skills (Python, SQL, AWS, Machine Learning) and classified messy text records into standardized organizational buckets (`Data Analyst`, `Data Engineer`, `Data Scientist`, `Machine Learning Engineer`).
4. **Business Intelligence Reporting:** Connected the optimized Snowflake analytical layer to Power BI to deliver interactive diagnostic dashboards mapping market share, geographical heatmaps, and role-specific skill frequencies.

### 🔹 Result
- **Market Discovery:** Identified that **Data Analyst** roles dominate total market volume at **33.5%**, closely tracked by Data Engineering positions.
- **Skill Dominance:** Quantified that **SQL** and **Python** represent absolute baseline baseline skills, maintaining standard prerequisite dominance across more than 65% of all aggregated data listings.
- **Architecture Efficiency:** Replaced rigid local spreadsheet tracking with an automated, transactional cloud data warehouse architecture capable of processing thousands of raw multi-line strings effortlessly.

---

## 🛠️ Tech Stack & Architecture Matrix
- **Language Layer:** Python (Pandas, NumPy, SQLAlchemy)
- **Cloud Infrastructure:** Snowflake Data Warehouse (Snowpark API integration)
- **Data Visualization & BI:** Power BI, Tableau Desktop
- **Development Tooling:** Jupyter Notebooks, Git Version Control

---

## 📂 Repository Blueprint & Execution Sequence

```text
├── etl_job_market.py                             # Repeatable USAJOBS → PostgreSQL ETL
├── Pipeline_for_Data_Job_Market_Analysis.ipynb   # Exploratory/notebook version of the pipeline
├── Job_Market_Analysis.ipynb                     # Exploratory data analysis
├── tests/test_etl_job_market.py                  # Offline ETL transformation tests
├── requirements.txt                              # Runtime dependencies
├── .env.example                                  # Safe environment-variable template
├── data/processed/                               # Generated CSV outputs (not committed)
├── airflow-jobs-pipeline/                        # Airflow orchestration experiments
└── README.md


## Run the ETL

The production-style command-line pipeline is `etl_job_market.py`. It fetches USAJOBS pages with connection reuse, bounded retry/backoff and explicit timeouts; normalizes and validates records in memory; then writes atomic CSV snapshots and upserts only the fetched IDs into PostgreSQL in a transaction. Job-to-skill matches are stored in a separate `job_posting_skills` bridge table, while `job_skills` remains the postings table for compatibility with the existing Power BI model. A zero-result extract never replaces existing database data.

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and populate the USAJOBS and PostgreSQL credentials. `.env` is ignored by Git.
3. Run `python etl_job_market.py` from this directory. CSVs are written to `data/processed/` by default.
4. For an API-and-transform run that writes CSVs without requiring PostgreSQL, run `python etl_job_market.py --skip-load`.
5. Run the offline checks with `python -m unittest discover -s tests`.

The ETL is incremental and idempotent per USAJOBS posting ID: the current API version is fetched, and only matching IDs are replaced, preserving older postings that are not in the latest API response. Salary values below $500 are treated as hourly and annualized at 2,080 hours, matching the analysis notebook's convention. `job_skills.csv` remains the clean postings export; skill matches are exported separately to `job_posting_skills.csv`.
