
````
# 📊 Federal Data Job Market Analysis & ETL Pipeline

An end-to-end data engineering and analytics project that collects, cleans, transforms, and analyzes federal data-related job postings from the **USAJOBS API**.

The project combines a modular Python ETL pipeline, PostgreSQL database, exploratory analysis, and Power BI dashboard to turn raw federal job postings into a structured dataset for understanding **job demand, salary, geography, employment type, and role distribution** across the U.S.

---

## 🔗 Project Links

* **✨ Live Project Walkthrough:** [Explore the Interactive Project Page](https://hatranusf.github.io/NextLeg/)
* **📁 GitHub Repository:** [View the Source Code](https://github.com/HaTranUSF/Job-Market-Analysis)
* **📊 Power BI Dashboard:** `Federal_Data_Job_Market_Analysis.pbix`

---

# 🎯 The Business Problem

The federal data job market contains thousands of postings across different agencies, each using varying job titles, unstructured descriptions, salary scales, and location formats.

Looking at individual postings makes it difficult to answer core questions like:

* Which data roles are federal agencies actively hiring for?
* How are opportunities distributed geographically?
* How does compensation compare across roles and employment types?
* What level of security clearance, financial access, or regulatory oversight is required for these roles?

Standard SQL can clean structured fields like titles and salaries, but it cannot query paragraph text inside job descriptions. Federal data roles often carry significant national security and compliance responsibilities, but you cannot determine that exposure from job titles alone.

### Core Business Question

> **How can we build a repeatable data pipeline that standardizes raw federal job postings into a reliable dataset for market analysis while automatically extracting risk and governance requirements locked in unstructured text?**

---

# 💡 The Solution

We built a production ETL pipeline paired with an experimental LLM enrichment processor:

1. **Extracts** raw job postings from the USAJOBS API with retry and pagination handling
2. **Transforms** raw records by standardizing job titles, pay scales, and state locations
3. **Classifies** roles into standardized categories (e.g., Data Engineer, Data Analyst)
4. **Normalizes** hourly and annual compensation into standardized salary bands
5. **Loads** cleaned data into PostgreSQL using transactional upserts
6. **Enriches** unstructured job descriptions using Gemini to extract compliance, clearance, and audit flags
7. **Verifies** LLM outputs against source text to prevent hallucinations before database insertion
8. **Visualizes** market trends and compliance risk across a two-page Power BI report

```text
                 USAJOBS API
                      │
                      ▼
              ┌──────────────┐
              │    Extract   │
              │  extract.py  │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │   Transform  │
              │ transform.py │
              └──────┬───────┘
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
   Job Standardization     Skill Extraction
          │                     │
          └──────────┬──────────┘
                     ▼
              ┌──────────────┐
              │     Load     │
              │    load.py   │
              └──────┬───────┘
                     │
                     ▼
           ┌──────────────────┐
           │    PostgreSQL    │
           └─────────┬────────┘
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
    Data Analysis      GenAI Risk Extraction
    (Jupyter Notebook)   (genai_enrichment.py)
          │                     │
          └──────────┬──────────┘
                     ▼
              ┌──────────────┐
              │   Power BI   │
              └──────────────┘

````

# 🧱 Databricks Medallion Setup

A Databricks-ready version of this project is available under [databricks_pipeline/README.md](databricks_pipeline/README.md). It implements the recommended Bronze → Silver → Gold pattern for USAJOBS data and is designed to feed Power BI from Delta tables.

Use the local workflow below to get started:

```bash
pip install -r requirements.txt
copy .env.example .env
python databricks_pipeline/run_pipeline.py
```

This writes raw job payloads to the Bronze layer, transforms them into normalized Silver tables, and creates Gold analytics tables for reporting.

---

# 📈 Dashboard & Key Findings

The Power BI dashboard is structured as a **macro-to-micro drilldown**: Page 1 tracks overall market distribution and compensation, while Page 2 analyzes internal compliance and governance risks.

### Page 1: Macro Market Overview

#### Key Findings (Macro Market):

- **Role Volume:** **Data Specialists** represent **60.1% (1.69K)** of open positions in the dataset, followed by **Data Analysts (16.89% / 0.48K)** and **Data Engineers (12.8% / 0.36K)**.
- **Compensation Averages:** Full-time positions average around **$116.16K**, whereas part-time roles average **$59.28K**. Average pay across all postings stayed above $110K throughout 2026.
- **Top Pay Bands:** **Machine Learning Engineers** and **Research Analysts** consistently command the highest mid-range salary tiers.

### Page 2: GenAI Risk & Audit Extraction (Experimental Feature)

> **Pilot Scope Note:** Page 2 is a proof-of-concept testing automated risk extraction on job descriptions. To stay within free API rate limits (`15 RPM`) and keep generation costs manageable during development, we processed a **pilot batch of 26 postings**. The python worker is built to process the entire PostgreSQL database in idempotent batches once scaled.

#### Key Findings (GenAI Risk Pilot):

- **Security & Financial Access:** Detected **3 explicit security clearance requirements** and **3 roles requiring access to sensitive financial systems** in the pilot sample.
- **Agency Risk Breakdown:** The **Department of the Air Force** and **Department of the Navy** had the highest volume of postings evaluated for audit controls, while independent agencies showed the highest concentration of internal control requirements (`mentions_audit_or_controls = 1`).
- **Source Grounding:** 100% of extracted risk flags are backed by exact quote snippets pulled directly from the job text.

# 📥 1. Data Extraction

The extraction script (`extract.py`) fetches federal data postings via the USAJOBS API.

Target job roles include:

- Data Analyst
- Data Scientist
- Data Engineer
- Business Analyst
- Machine Learning Engineer
- Analytics Engineer
- Data Specialist
- Research Analyst
- Business Intelligence Analyst
- Data Architect
- Data Warehouse Engineer
- Database Administrator

To handle API constraints reliably, the script uses persistent HTTP sessions, pagination, explicit request timeouts, and exponential backoff retries for transient errors. The reference dataset captured **5,588 raw postings**.

# 🧹 2. Data Transformation

The transformation module (`transform.py`) cleans messy API payloads into a tabular format:

- **Role Classification:** Rule-based title parsing maps varied agency titles into standard data career tracks.
- **Location Parsing:** Extracts city and state data, keeping only U.S. states and Washington, D.C.
- **Salary Normalization:** Converts hourly rates (<$500) to annual values assuming 2,080 working hours per year.
- **Field Standardization:** Standardizes dates, employment types (full-time, part-time, shift work), and remote eligibility.

# 🔗 3. Skill Extraction

Skills are parsed from posting descriptions and stored in a normalized junction table (`job_posting_skills`).

Because keyword extraction from free-text postings can be noisy, skill frequency data was excluded from the primary dashboard to keep the market findings accurate.

# 🗄️ 4. PostgreSQL Data Layer & Loading

Database creation is managed by `engine.py`, and data loading is handled by `load.py`.

### Primary Tables

- **`job_skills`**: Stores primary posting records (title, organization, salary, location, description).
- **`job_posting_skills`**: Bridge table mapping job postings to extracted skill keywords.
- **`job_risk_attributes`**: Stores structured flags, system lists, and text quotes extracted by the Gemini module.
- **`vw_job_risk_evidence`**: Reporting view joining posting metadata with risk extraction flags for Power BI.

### Loading Logic

- **Transactional Updates:** Refreshes active postings without dropping historical records.
- **Content Deduplication:** Checks hashed description content to catch duplicate postings published under different job IDs.
- **Constraint Protection:** Uses unique indexes on posting IDs and skill pairs to prevent duplicate rows during pipeline reruns.

# 🤖 5. GenAI Risk Evidence Processor

The enrichment runner (`genai_enrichment.py`) scans unstructured job descriptions to identify operational risks, required clearance levels, and regulatory responsibilities.

Plaintext

```
┌─────────────────┐
│  USAJOBS API    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Python ETL     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ PostgreSQL (job_skills) │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────┐
│ genai_enrichment.py │
└────────┬────────────┘
         │
         ▼
┌───────────────────────────┐
│ Gemini Python SDK         │
│ (gemini-3.5-flash-lite)   │
└────────┬──────────────────┘
         │
         ▼
┌─────────────────────────────┐
│ Validated Risk Evidence     │
└────────┬────────────────────┘
         │
         ▼
┌────────────────────────────────────┐
│ PostgreSQL (job_risk_attributes)   │
└────────┬───────────────────────────┘
         │
         ▼
┌──────────────────────────┐
│  vw_job_risk_evidence    │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────┐
│   Power BI       │
└──────────────────┘

```

### How It Works

1. **Schema Validation:** Uses Pydantic and the `google-genai` SDK to force Gemini into returning structured JSON matching our database schema.
2. **Zero-Hallucination Grounding:** A validation function (`validate_response`) checks every extracted quote against the original job description text. If a quote is hallucinated or modified by the model, the flag is reset to `False`.
3. **Idempotent Batch Runs:** The worker hashes each description (`MD5`). Rerunning the script skips unchanged descriptions and only processes new or updated postings.

### Running the Enrichment Worker

PowerShell

```
# Ingest up to 10 unprocessed postings
python genai_enrichment.py --limit 10

# Force re-enrichment on a specific batch
python genai_enrichment.py --force --limit 10

```

# 🧪 6. Data Quality & Testing

Unit tests are located in the `tests/` directory:

- **`test_etl_job_market.py`**: Validates salary normalization, date parsing, location cleanup, and deduplication logic.
- **`test_genai_enrichment.py`**: Tests response validation, quote verification, rate-limit retries, and database upserts using mocked API responses.

Run the test suite:

Bash

```
python -m unittest discover -s tests

```

# 📂 7. Repository Structure

Plaintext

```
Job-Market-Analysis/
│
├── etl_job_market.py      # ETL pipeline orchestrator
├── extract.py             # USAJOBS API extractor
├── transform.py           # Data cleaning & normalization
├── load.py                # Database upsert logic
├── genai_enrichment.py    # Gemini risk extraction worker
├── engine.py              # PostgreSQL engine & table schemas
│
├── tests/                 # Unit test suite
│   ├── test_etl_job_market.py
│   └── test_genai_enrichment.py
│
├── experimentation/       # Analysis notebooks
│   └── Pipeline_for_Data_Job_Market_Analysis.ipynb
│
├── Federal_Data_Job_Market_Analysis.pbix  # Power BI report
├── Dashboard.png          # Page 1 preview
├── GenAI_dashboard.png    # Page 2 preview
├── requirements.txt       # Dependencies
└── README.md

```

# 🚀 8. How to Run

1. **Clone the repository:**

   Bash
   ```
   git clone [https://github.com/HaTranUSF/Job-Market-Analysis.git](https://github.com/HaTranUSF/Job-Market-Analysis.git)
   cd Job-Market-Analysis

   ```
2. **Install dependencies:**

   Bash
   ```
   pip install -r requirements.txt

   ```
3. **Configure environment variables:**
   Create a `.env` file from `.env.example` and add your database credentials and API keys:

   Code snippet
   ```
   USAJOBS_API_KEY=your_key
   USAJOBS_EMAIL=your_email
   POSTGRES_DB=job_market
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=your_password
   GEMINI_API_KEY=your_gemini_key

   ```
4. **Run the full ETL pipeline:**

   Bash
   ```
   python etl_job_market.py

   ```
5. **Run without loading to PostgreSQL:**

   Bash
   ```
   python etl_job_market.py --skip-load

   ```

# 🧠 9. Key Project Takeaways

This project shows how standard ETL patterns can be combined with structured LLM parsing to analyze messy enterprise data:

- **Structured Data:** Ingests and normalizes thousands of API records for standard business metrics (pay, location, volume).
- **Unstructured Context:** Uses LLMs to unlock operational details (clearances, financial access) buried in raw paragraph text.
- **Data Verification:** Uses string validation to ensure AI outputs are grounded in exact source text before reaching the database.
