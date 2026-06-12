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
├── Pipeline_for_Data_Job_Market_Analysis.ipynb   # Cloud pipeline, connection, & Snowflake loading script
├── Job_Market_Analysis.ipynb                     # Local Exploratory Data Analysis & Feature Engineering
├── job_postings.csv                              # Raw baseline tracking index (12,000+ rows)
├── job_skills.csv                                # Raw extracted keyword token files
├── dashboard_preview.png                         # Screenshot of your live Power BI Dashboard
├── index.html                                    # Standalone Portfolio landing page code
└── README.md                                     # Main repository index documentation
