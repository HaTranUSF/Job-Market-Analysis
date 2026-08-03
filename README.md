# Federal Data Job Market Pipeline

An automated pipeline that pulls live federal data-role job postings from the USAJobs API, cleans and classifies them, loads them into PostgreSQL, and surfaces the results in an interactive Power BI dashboard.

## The Business Problem

The federal government posts thousands of data-related jobs on USAJobs, but the postings are messy: the same role gets fifty different title variations ("Data Analyst," "Program Analyst (Data Analyst)," "IT Specialist (Data Management)"), pay is listed as either an annual range or an hourly rate depending on the agency, and location fields mix single cities, "Multiple Locations," and international postings with no consistent format. Anyone trying to answer a simple question, like which agencies are hiring the most data talent right now, where the pay is highest, or which roles are growing, has to manually dig through hundreds of listings one at a time. There's no clean, queryable view of the federal data job market.

## What I Built

A pipeline that turns that mess into a structured dataset and a dashboard that answers those questions directly.

**Extract:** Pulled postings from the USAJobs API across 12 data-related role searches (data analyst, data engineer, data scientist, business analyst, ML engineer, analytics engineer, and others), paginating through results until each search was exhausted. This returned 5,588 raw postings.

**Transform:**
- Deduplicated on posting ID (5,588 → 2,839 unique postings)
- Classified each posting into a standardized role bucket using a rules-based function on the job title, filtering out non-data roles that slipped into the search results (mechanics, drivers, clerks, etc.)
- Normalized salary: some postings list an hourly rate instead of an annual salary, so I detected and converted those to be comparable
- Standardized dates, employment type codes, and job grade into readable formats
- Split location into city and state, and filtered out non-US and malformed entries, landing on 816 clean, US-based postings with complete data across all fields

**Load:** Wrote the cleaned dataset into a PostgreSQL table, with logic to check for an existing table, merge in new postings, and drop duplicates on ID, so re-running the pipeline updates the dataset instead of overwriting it from scratch.

**Report:** Connected Power BI to the Postgres table to build a dashboard with a US map of job postings by state, a US map of average salary by state, salary by role, salary by employment type, a compensation trend line, and nationwide job counts.

## Key Decisions Along the Way

**Snowflake to Postgres.** I originally built this on Snowflake, but the compute cost wasn't justified for a personal project at this data volume. I moved the pipeline to Postgres, which does the job for free at this scale without giving up the incremental-load pattern.

**Skill extraction didn't make the cut.** I wanted the dashboard to also show which specific skills (Python, SQL, AWS, etc.) show up most across postings. I tried two approaches: TF-IDF scoring on the job descriptions, and a regex keyword match against a fixed skill list. Neither produced clean results; TF-IDF surfaced generic high-frequency words instead of real skills, and the regex list missed skills phrased differently across postings. Rather than ship a noisy skills chart, I left it out of this version. [Next step: rebuild this with a better keyword-matching approach, or fine-tune the skill list against the actual description text before adding it back to the dashboard.]

## Results

- Pulled 5,588 postings across 12 federal data-role searches and cleaned them down to a final dataset of 950 actively hiring, US-based listings
- **Data Analyst (34.5%) and Data Engineer (32.1%) dominate the market**, together accounting for roughly two-thirds of all actively hiring federal data postings
- **Data Specialist (~12.3%) and Data Scientist (11%) form the next tier**, with data architect, research analyst, business analyst, database administrator, data warehouse engineer, and machine learning engineer each making up a small remaining slice
- **Virginia leads both job volume and average salary**, consistent with the concentration of DC-metro federal agencies headquartered there
- **Shift Work postings carry the highest average salary ($122.4K)**, slightly ahead of Full-Time ($120K) and On-Call ($108.9K), while Part-Time trails well behind at $39.3K, a useful counter to the assumption that full-time roles always pay best
- **Average salary is fairly consistent across roles** rather than showing a dramatic gap between, say, Data Analyst and Machine Learning Engineer, suggesting federal pay bands compress role-based salary variation more than the private sector does
- **Compensation fluctuated notably month to month** (roughly $95K to $138K between Oct 2025 and Jul 2026) without a clean upward or downward trend, which tracks with a relatively small monthly posting volume rather than a real seasonal signal

## Tech Stack

- **Ingestion:** Python, USAJobs API, `requests`
- **Transformation:** Python, pandas, NumPy
- **Storage:** PostgreSQL, SQLAlchemy, psycopg2
- **Reporting:** Power BI
- **Config/secrets:** python-dotenv

## Repository Structure

```text
├── Pipeline_for_Data_Job_Market_Analysis.ipynb   # Extract, transform, and load into Postgres
├── Federal_Data_Job_Market_Analysis.pbix         # Power BI dashboard
└── README.md
```

## What's Next

- Fix the "Nationwide Job Counts" card, which is currently rendering blank on the dashboard
- Add a working skill-extraction step so the dashboard can show top in-demand skills by role
- Automate the pipeline to run on a schedule instead of manually
- Expand beyond federal postings if a broader private-sector comparison is useful
