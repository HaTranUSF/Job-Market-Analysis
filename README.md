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

The federal data job market contains thousands of job postings with different titles, descriptions, salary formats, employment types, and locations.

Looking at individual postings makes it difficult to answer broader questions such as:

* Which data-related roles account for the largest share of opportunities?
* How are opportunities distributed geographically?
* How does compensation vary across roles?
* How does salary differ by employment type?
* What does the current federal data-job market look like after standardizing inconsistent source data?

The challenge is therefore not simply collecting job postings. It is turning messy, semi-structured job data into a consistent dataset that can support meaningful analysis.

### Business Question

> **How can we build a repeatable data pipeline that transforms raw federal job postings into a reliable dataset for analyzing data-job demand, compensation, and geographic patterns?**

---

# 💡 The Solution

We built a production-style ETL pipeline that:

1. **Extracts** job postings from the USAJOBS API
2. **Transforms** raw postings into standardized analytical records
3. **Classifies** postings into data-related job categories
4. **Normalizes** compensation and other fields
5. **Filters** the dataset to U.S.-based data-related positions
6. **Loads** the cleaned data into PostgreSQL
7. **Exports** database snapshots for downstream use
8. **Analyzes** the resulting dataset through exploratory analysis
9. **Visualizes** the results in Power BI

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
                PostgreSQL
                     │
            ┌────────┴────────┐
            ▼                 ▼
      Data Analysis       CSV Snapshots
            │
            ▼
        Power BI
```

---

# 📥 1. Data Extraction

The pipeline uses the **USAJOBS API** to retrieve federal job postings associated with data-related roles.

The extraction workflow is implemented in:

```text
extract.py
```

The pipeline searches across a defined set of data-related roles, including:

* Data Analyst
* Data Scientist
* Data Engineer
* Business Analyst
* Machine Learning Engineer
* Analytics Engineer
* Data Specialist
* Research Analyst
* Business Intelligence Analyst
* Data Architect
* Data Warehouse Engineer
* Database Administrator

The extraction process includes several safeguards for working with an external API:

* API pagination
* Persistent HTTP connections
* Explicit request timeouts
* Bounded retry and backoff behavior
* Handling of temporary API errors
* Tracking of fetched posting IDs

The recorded notebook extraction contains **5,588 raw postings** before the subsequent transformation and filtering steps.

---

# 🧹 2. Data Transformation

Raw USAJOBS postings contain inconsistent titles, descriptions, locations, dates, salary formats, and other fields.

The transformation workflow is implemented in:

```text
transform.py
```

It converts the raw API response into a structured analytical dataset.

### Role Classification

The pipeline applies rules-based classification to standardize job titles into data-related categories.

The classification logic distinguishes roles such as:

* Data Analyst
* Data Engineer
* Data Scientist
* Machine Learning Engineer
* Analytics Engineer
* Business Analyst
* Business Intelligence Analyst
* Data Architect
* Data Warehouse Engineer
* Database Administrator
* Data Specialist
* Research Analyst

The transformation also applies exclusions to prevent unrelated postings from being included in the analytical dataset.

### Location Standardization

Location information is parsed into structured geographic fields.

The analysis is restricted to U.S. locations, including the 50 states and Washington, D.C.

### Salary Normalization

Salary information is converted into a consistent annualized representation.

For salary values below `$500`, the pipeline treats the value as an hourly rate and annualizes it using:

```text
2,080 hours/year
```

This matches the convention used in the analysis notebook.

### Date and Employment Standardization

The pipeline also standardizes fields such as:

* Application dates
* Start dates
* Employment type
* Job grade
* Remote status
* Location

---

# 🔗 3. Skill Extraction

The transformation pipeline also creates structured job-to-skill relationships.

Skills are extracted from job-posting content and stored separately from the main job records.

The database uses:

```text
job_skills
```

for job postings and:

```text
job_posting_skills
```

as the bridge table connecting postings to extracted skills.

This creates a many-to-many relationship between jobs and skills.

### Important Limitation

Skill extraction was explored as part of the project, but the resulting skill data was not considered reliable enough to use for the primary dashboard analysis.

The project therefore does **not** make claims about overall skill dominance such as "SQL appears in X% of postings."

This was an intentional data-quality decision rather than presenting potentially noisy skill results as definitive market findings.

---

# 🗄️ 4. PostgreSQL Data Layer

The current production pipeline uses **PostgreSQL** as its database.

Database configuration and schema creation are handled by:

```text
engine.py
```

The loading process is implemented in:

```text
load.py
```

The primary tables are:

### `job_skills`

Contains the structured job-posting records, including fields such as:

* Job ID
* Role
* Title
* Organization
* Department
* City
* State
* Description
* Posting dates
* Salary
* Employment type
* Remote status

### `job_posting_skills`

A bridge table containing relationships between job postings and extracted skills.

This structure allows one job posting to be associated with multiple skills.

---

# 🔄 5. Incremental & Transactional Loading

The pipeline is designed to update the current dataset without simply replacing the entire database.

The loader:

* Refreshes postings returned by the latest API extraction
* Preserves older postings that are not returned by the latest response
* Uses database transactions during loading
* Removes duplicate job-skill relationships
* Protects posting IDs and job-skill pairs with unique indexes
* Prevents a zero-result extraction from replacing existing data

### Content-Based Deduplication

The pipeline also checks for duplicate postings based on their posting content rather than relying only on the source ID.

This helps identify cases where identical job postings appear under different source IDs.

---

# 📊 6. Exploratory Data Analysis

The exploratory analysis is documented in:

```text
experimentation/Pipeline_for_Data_Job_Market_Analysis.ipynb
```

The notebook examines the transformed job dataset and supports the analysis presented in the dashboard.

Areas explored include:

* Job role distribution
* Salary patterns
* Geographic distribution
* Employment type
* Job grades
* Data volume through the transformation pipeline

The notebook also contains the project's earlier pipeline experimentation and transformation work.

---

# 📈 7. Power BI Dashboard

The final analytical output is presented through Power BI.

The dashboard is designed around several business questions.

### Job Market Distribution

Examines the distribution of federal data-related job postings across role categories.

In the current dashboard analysis:

* **Data Analyst:** 34.5%
* **Data Engineer:** 32.1%

Together, these two categories represent **66.6%** of the analyzed postings.

### Geographic Analysis

The dashboard examines:

* Job postings by state
* Average salary by state
* Geographic concentration of opportunities

### Compensation Analysis

The dashboard compares compensation across:

* Job roles
* States
* Employment types
* Other available job attributes

### Employment Analysis

The dashboard provides an overview of job volume and compensation patterns across different employment types.

---

# 📌 Key Findings

Based on the current dashboard and project analysis:

### Data Analyst & Data Engineer Roles

Data Analyst and Data Engineer positions make up the largest portions of the analyzed dataset, accounting for **34.5%** and **32.1%**, respectively.

Together, they represent **66.6%** of the analyzed postings.

### Geographic Variation

Job opportunities and average compensation vary across U.S. states, providing a way to compare where federal data-related positions are concentrated and how compensation differs geographically.

### Role-Level Compensation

Salary distributions differ across job categories, allowing the dashboard to be used to compare compensation patterns between different data-related career paths.

> These findings describe the dataset collected through the USAJOBS-based pipeline. They should not be interpreted as a complete representation of the entire U.S. or global data-job market.

---

# 🧪 8. Data Quality & Testing

The project includes an offline test suite:

```text
tests/test_etl_job_market.py
```

The tests cover important transformation and loading behaviors, including:

* Posting deduplication
* Salary normalization
* Job-grade processing
* Employment-type processing
* Date parsing
* Location parsing
* Skill extraction

Run the test suite with:

```bash
python -m unittest discover -s tests
```

---

# 📤 9. Data Outputs

The ETL pipeline can generate database snapshots under:

```text
data/processed/
```

The generated outputs include:

```text
job_skills.csv
job_posting_skills.csv
```

`job_skills.csv` contains the persisted job-posting records.

`job_posting_skills.csv` contains the relationships between job postings and extracted skills.

The generated CSV files are ignored by Git and are not part of the committed repository.

---

# 🏗️ 10. Pipeline Architecture

The production pipeline is organized into modular Python components:

```text
extract.py
    │
    ├── USAJOBS API requests
    ├── Pagination
    ├── Retry / backoff
    └── Raw posting extraction
          │
          ▼
transform.py
    │
    ├── Data cleaning
    ├── Role classification
    ├── Location parsing
    ├── Salary normalization
    ├── Date normalization
    └── Skill extraction
          │
          ▼
load.py
    │
    ├── Transactional database updates
    ├── Posting replacement
    └── Skill relationship loading
          │
          ▼
engine.py
    │
    ├── PostgreSQL connection
    ├── Table definitions
    └── Unique indexes
          │
          ▼
PostgreSQL
          │
          ├──────────────► CSV snapshots
          │
          ▼
      Power BI
```

The entire workflow is orchestrated through:

```text
etl_job_market.py
```

---

# 📂 11. Repository Structure

```text
Job-Market-Analysis/
│
├── etl_job_market.py
│   └── ETL pipeline orchestrator
│
├── extract.py
│   └── USAJOBS API extraction
│
├── transform.py
│   └── Data cleaning, classification,
│       normalization, and skill extraction
│
├── load.py
│   └── PostgreSQL loading logic
│
├── engine.py
│   └── Database connection and schema definitions
│
├── tests/
│   └── test_etl_job_market.py
│       └── Offline ETL tests
│
├── experimentation/
│   ├── Pipeline_for_Data_Job_Market_Analysis.ipynb
│   └── airflow-jobs-pipeline/
│
├── Federal_Data_Job_Market_Analysis.pbix
│   └── Power BI dashboard
│
├── Dashboard.png
│   └── Dashboard preview
│
├── index.html
│   └── Interactive project walkthrough
│
├── requirements.txt
│   └── Python dependencies
│
├── .env.example
│   └── Environment variable template
│
├── .gitignore
│
└── README.md
```

---

# 🚀 12. Running the Pipeline

## Step 1: Clone the Repository

```bash
git clone https://github.com/HaTranUSF/Job-Market-Analysis.git
cd Job-Market-Analysis
```

## Step 2: Create the Environment

Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Step 3: Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Configure the required USAJOBS and PostgreSQL credentials.

Do not commit `.env` to Git.

## Step 4: Run the Full ETL Pipeline

```bash
python etl_job_market.py
```

The pipeline will:

1. Extract USAJOBS postings
2. Transform and standardize the data
3. Load the results into PostgreSQL
4. Generate CSV snapshots from the persisted database data

## Step 5: Run Without PostgreSQL

To perform extraction and transformation without loading the database:

```bash
python etl_job_market.py --skip-load
```

## Step 6: Run Tests

```bash
python -m unittest discover -s tests
```

---

# 💰 13. Architecture Evolution

The project originally used **Snowflake** during development.

After evaluating the scale and requirements of the project, the implementation was moved to **PostgreSQL**.

This resulted in a simpler architecture for the current dataset while preserving the modular ETL design.

```text
Original Prototype
Snowflake
    ↓
Evaluation of project scale/cost
    ↓
Current Implementation
PostgreSQL
```

The current repository therefore uses PostgreSQL as the production data layer. Snowflake is part of the project's development history rather than the current implementation.

---

# 🔮 14. Future Improvements

Potential next steps identified during the project include:

* Automating scheduled pipeline execution
* Expanding the number of data sources
* Improving skill extraction and validation
* Adding more robust historical job tracking
* Expanding analytical coverage
* Further improving the dashboard experience

---

# 🧠 15. Project Takeaway

This project demonstrates how a messy, semi-structured job-posting source can be transformed into a repeatable analytical workflow.

The core process is:

```text
USAJOBS API
     ↓
Extract
     ↓
Clean & Standardize
     ↓
Classify
     ↓
Normalize
     ↓
PostgreSQL
     ↓
Analyze
     ↓
Power BI
```

Rather than manually reviewing individual job postings, the pipeline creates a structured foundation for analyzing **which federal data roles are most common, where opportunities are concentrated, and how compensation varies across the market**.

The project combines data engineering and analytics to turn raw job-posting data into a business-facing data product.
