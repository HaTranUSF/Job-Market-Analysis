# 📊 Federal Data Job Market Analysis & ETL Pipeline

This project collects federal data job postings from the USAJOBS API, cleans them with Python, and stores them in PostgreSQL for analysis in Power BI. It looks at hiring demand, salaries, locations, and employment types across federal agencies.

An experimental Gemini worker also reads job descriptions for security clearance, financial access, and audit requirements. It checks extracted quotes against the source text before saving the results.

## Project links

- [Interactive project walkthrough](https://hatranusf.github.io/NextLeg/)
- [GitHub repository](https://github.com/HaTranUSF/Job-Market-Analysis)
- [Power BI report](Federal_Data_Job_Market_Analysis.pbix)

## What the project looks at

Federal agencies use different titles, salary formats, and location descriptions for similar jobs. Cleaning those fields makes it easier to compare postings and answer questions such as:

- Which data roles have the most openings?
- Where are those jobs located?
- How does pay vary by role and employment type?
- Which postings mention clearance, financial systems, or audit responsibilities?

## Pipeline

```text
USAJOBS API
    |
    v
Extract -> Transform -> PostgreSQL -> Analysis and Power BI
                            |
                            v
                    Gemini enrichment
                            |
                            v
                  Risk evidence reporting
```

### Extraction and cleaning

`extract.py` fetches postings with pagination, request timeouts, and retries. The reference dataset contained 5,588 raw postings.

`transform.py` maps job titles to standard role categories, parses U.S. locations, and standardizes dates, employment types, and remote eligibility. Hourly salaries below $500 are converted to annual estimates using 2,080 working hours per year.

The search covers Data Analyst, Data Scientist, Data Engineer, Business Analyst, Machine Learning Engineer, Analytics Engineer, Data Specialist, Research Analyst, Business Intelligence Analyst, Data Architect, Data Warehouse Engineer, and Database Administrator roles.

Skills are extracted from descriptions and stored in `job_posting_skills`. They are excluded from the main dashboard because keyword matches can be noisy.

### Database loading

`engine.py` defines the database tables, and `load.py` loads the cleaned records. Transactional upserts refresh existing postings while retaining historical records. Description hashes help identify duplicate content, and unique indexes prevent duplicate posting IDs and skill pairs.

| Table or view | Contents |
| --- | --- |
| `job_skills` | Posting titles, agencies, salaries, locations, and descriptions |
| `job_posting_skills` | Links between postings and extracted skills |
| `job_risk_attributes` | Risk flags, system names, and supporting quotes |
| `vw_job_risk_evidence` | Posting metadata and risk evidence for Power BI |

### Experimental risk extraction

`genai_enrichment.py` uses Gemini to extract clearance, financial access, and audit requirements from job descriptions.

- Pydantic and a response schema define the expected JSON structure.
- `validate_response` checks supporting quotes against the original description and resets flags when the quotes fail validation.
- Description hashes let later runs skip unchanged postings.

Quote checks help catch unsupported evidence, but they do not guarantee that every interpretation is correct.

## Dashboard findings

The Power BI report has two pages. The first covers hiring volume, geography, and compensation. The second shows the risk extraction pilot.

### Job market overview

The report's dataset showed:

- Data Specialists accounted for 60.1% of openings, about 1.69K postings. Data Analysts made up 16.89%, about 0.48K, and Data Engineers made up 12.8%, about 0.36K.
- Full-time positions averaged about $116.16K, compared with $59.28K for part-time positions.
- Machine Learning Engineers and Research Analysts had the highest mid-range salary tiers.

These figures describe the report's dataset and are not a live count of federal openings.

### Risk extraction pilot

The pilot processed 26 postings to limit API usage during development. It found three explicit clearance requirements and three roles requiring access to sensitive financial systems.

The Department of the Air Force and Department of the Navy had the most postings evaluated for audit controls in the sample. Independent agencies had the highest concentration of internal control mentions. The report records supporting source quotes for the extracted flags.

The sample is small, so these results describe the pilot rather than the wider federal job market.

## Setup

Run these commands from the repository root.

1. Clone the repository:

   ```bash
   git clone https://github.com/HaTranUSF/Job-Market-Analysis.git
   cd Job-Market-Analysis
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your credentials. In PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   The pipeline uses these settings:

   ```dotenv
   USAJOBS_USER_AGENT=your-contact-email-or-application-name
   USAJOBS_AUTH_KEY=your-usajobs-api-key
   DB_USER=your-postgres-user
   DB_PASSWORD=your-postgres-password
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=job_market
   ```

   Create the PostgreSQL database before running the load step. For optional risk enrichment, also set `GEMINI_API_KEY` and, if needed, `GEMINI_MODEL` in `.env`.

4. Run the ETL pipeline:

   ```bash
   python etl_job_market.py
   ```

   To run extraction and transformation without loading PostgreSQL:

   ```bash
   python etl_job_market.py --skip-load
   ```

5. Run the optional enrichment worker after loading postings:

   ```bash
   python genai_enrichment.py --limit 10
   ```

   To reprocess a batch:

   ```bash
   python genai_enrichment.py --force --limit 10
   ```

## Tests

The tests cover salary normalization, date and location parsing, deduplication, enrichment response validation, quote checks, retries, and database upserts. API responses are mocked in the enrichment tests.

```bash
python -m unittest discover -s tests
```

## Repository structure

```text
Job-Market-Analysis/
  etl_job_market.py       # Pipeline runner
  extract.py              # USAJOBS API requests
  transform.py            # Cleaning and normalization
  load.py                 # PostgreSQL loading
  engine.py               # Database connection and schemas
  genai_enrichment.py     # Experimental risk extraction
  tests/                  # Unit tests
  experimentation/        # Analysis notebooks
  Federal_Data_Job_Market_Analysis.pbix
  Dashboard.png           # Market overview preview
  GenAI_dashboard.png     # Risk extraction preview
  requirements.txt
  .env.example
  README.md
```
