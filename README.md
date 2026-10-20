# 📊 Data Job Market Analysis & ETL Pipeline

## Company sources: Greenhouse, Lever, and AshbyHQ

The pipeline now defaults to public company job boards. It downloads the
[ATS directory](https://github.com/moonie0201/ats-directory) (`companies.jsonl`,
CC0-1.0), selects all listed Greenhouse, Lever, and Ashby boards, and fetches
postings directly from their public APIs. No ATS API keys or employer accounts
are required. The directory supplies board identifiers and Lever regions.

Collect a small sample without PostgreSQL:

```powershell
python -m pip install -r requirements.txt
python etl_job_market.py --skip-load --board-limit 5 --output-dir data/sample
```

`--board-limit` limits boards **per provider**, defaulting to `0` (all boards).
Previously dead or unconfirmed boards are retried too. To choose providers:

```powershell
python etl_job_market.py --skip-load --providers greenhouse lever ashby --board-limit 0
```

Four workers collect boards with a shared request gate and bounded HTTP retries.
`--workers` accepts 1 through 16. `--active-boards-only` restricts collection to
boards the directory last marked `ok`. Board counts are not unique company counts:
one employer can have multiple boards, and the public directory is not exhaustive.

The directory is cached in `data/directory/companies.jsonl`, with retrieval time,
source URL, license, and SHA-256 in `companies.metadata.json`. Use
`--refresh-directory` to download a new snapshot, or `--directory-path` for a
saved JSONL directory. Original slug capitalization is preserved.

Each run creates an immutable `data/runs/<UTC-run-id>/` folder containing:

| Artifact | Purpose |
| --- | --- |
| `manifest.json` | Frozen boards, configuration, directory hash, run status, and summary |
| `directory.jsonl` | Original company directory used for that run |
| `raw/*.json.gz` | Compressed original postings for every successfully fetched board, including roles and countries excluded from analysis |
| `boards/*.json` | Per-board checkpoints, timestamps, counts, and errors |
| `job_skills.csv` | Normalized U.S. data-role postings, with `run_id` and `board_key` |
| `job_posting_skills.csv` | One row per run/job/skill match |
| `board_report.json` | All boards, including empty, failed, and transformation-failed boards |
| `summary.json` | Provider coverage, posting counts, skill counts, and missing-field counts |

Successful boards checkpoint immediately. Resume an interrupted run without
refetching successful boards:

```powershell
python etl_job_market.py --resume data/runs/<run-id>
```

To apply updated normalization to saved raw data without fetching boards again:

```powershell
python etl_job_market.py --reprocess data/runs/<run-id> --load
```

Reprocessing creates a new local run, records the original `collection_id`, source
run, and transformation fingerprint, and preserves collection timestamps.
PostgreSQL keeps one processed version per collection: loading a newer version
replaces the older version transactionally, with a backup under `data/backups/`.
Loading an older version over a newer one is rejected. A fresh API collection
gets a new collection ID and adds another historical observation.

For an interrupted run, `--retry-failed` also retries failed boards. Finalized
runs cannot be modified; start a new run to retry them. Resume always uses the
original board list and geography settings. A process lock prevents simultaneous
writers to the same run. Raw data, directory caches, and exports are gitignored.

Convenient copies are published to `data/processed/` (or `--output-dir`).
`jobs_overview.csv` is a compact, one-line-per-job view with combined skills and
no long description or technical metadata. Use it for browsing in an editor or
Excel. The complete `job_skills.csv` keeps quoted multiline descriptions and
all provenance fields for analysis; physical text lines are not CSV row counts.
`latest.json` points to the coherent, dated snapshot. `partial` means at least one
board failed and the exports contain only successful boards. All-board failure
preserves previous latest exports; a successful empty response is valid data.
Runs are collection windows, not simultaneous observations. Re-run periodically
to build history; older closed jobs cannot be recovered from the public APIs.

Titles are filtered for data, analytics, BI, business analyst, ML, database, ETL,
and research analyst roles. Geography defaults to U.S. postings identified by a
structured country or recognizable U.S. location. Secondary Ashby locations,
Lever's location list, and Greenhouse offices are also checked, and all locations
are retained in `locations_json`. Ambiguous locations,
including generic remote locations, are excluded. `--include-unknown-country`
retains these with an empty country; they are not confirmed U.S. opportunities.

Provenance includes provider, board, original ID, source/application URLs,
location, workplace type, and collection time. Stable namespaced IDs prevent
collisions. Missing pay and dates stay empty. Greenhouse's update date is stored
separately from publication dates; Ashby's date means last publication. ATS
salaries retain original values and currency. `salary_period_raw` preserves the
source period while `salary_period` standardizes known units. Separate
`salary_min_annual_usd` and `salary_max_annual_usd` fields estimate annual USD pay
only for explicit USD currencies and known periods (12 months, 52 weeks,
260 days, or 2,080 hours per year). They are estimates, not guaranteed annual
earnings. No exchange-rate conversion is performed. Greenhouse description-only
pay is not parsed. Ashby salary is
used only when one unambiguous summary salary component is supplied. Compare
pay only within compatible currencies and periods.

For PostgreSQL loading, fill in `DB_*` settings in `.env` and use `--load`.
Local collection is the default and needs no credentials. A saved run can be
loaded later without network calls to job boards:

```powershell
python etl_job_market.py --load
python etl_job_market.py --resume data/runs/<run-id> --load
```

The loader stores company job snapshots in the following tables. Each run loads in one transaction; reloading an identical run is a no-op.
A conflicting fingerprint for an existing run ID is rejected.

```text
Company directory -> Parallel board requests -> Raw checkpoints
                                                    |
                                                    v
                                             Normalize + filter
                                                    |
                                                    v
                                         Dated jobs + skills + coverage
                                                    |
                                                    v
                                  PostgreSQL snapshot history -> Power BI views
```

| PostgreSQL object | Contents |
| --- | --- |
| `market_runs` | Run metadata, configuration, coverage, and content fingerprint |
| `market_board_runs` | Every attempted board and its outcome, including zero-job boards |
| `market_job_postings` | Historical posting snapshots keyed by `(run_id, id)` |
| `market_job_skills` | Historical skill matches keyed by `(run_id, job_id, skill)` |
| `vw_market_current_jobs` | Postings from each board's latest successful observation |
| `vw_market_current_skills` | Skill matches for the current-job view |
| `vw_market_job_history` | First/last observed dates, snapshot count, content-version count |
| `vw_market_board_coverage` | Per-run and per-provider coverage totals |

Current views retain the previous successful observation for failed boards;
check `collected_at` for freshness. A later successful empty board removes its
previous postings from the current view, while keeping history. These are observed
listing states, not verified vacancy/closure dates. The normalized dataset is
filtered by role and country, so disappearing from it can also mean a title or
location changed. Stable IDs do not deduplicate employers across ATS migrations.

Connect Power BI to `vw_market_current_jobs` and `vw_market_current_skills` using
`(run_id, id)` to `(run_id, job_id)`. Because Power BI relationships use one column,
create a combined key in Power Query, or join on `id` when using only these current
views. Use the history tables and coverage view for trends. The preserved [Power BI dashboard](Federal_Data_Job_Market_Analysis.pbix) remains available as a reference artifact.

### New pipeline modules and validation

Stage-specific files live in folders named after their ETL stage. Shared modules
stay at the repository root:

```text
extract/
  collect_market.py       # Directory snapshot, API collection, checkpoints, resume
transform/
  market_snapshot.py      # Normalize saved responses, filter, export jobs/skills
  job_features.py         # Role classification and skill keyword matching
load/
  market_store.py         # Transactional PostgreSQL history and reporting views
etl_job_market.py         # Runs extract -> transform -> load
ats_sources.py            # Shared API adapters and source normalization
job_fields.py             # Shared posting column definitions
http_client.py            # Shared HTTP requests and retries
database.py               # Shared PostgreSQL connection configuration
pipeline_io.py            # Shared board IDs, atomic writes, locking
verify_market.py          # Validates local exports and database counts
sql/market_analysis.sql   # Read-only analysis queries
tests/                    # Unit and PostgreSQL integration tests
```

`ats_sources.py` stays outside the stage folders because both extraction and
transformation use it. Shared configuration, schema definitions, and file/database
utilities also stay outside. Run commands from the repository root as before.

```powershell
python -m unittest discover -s tests
# Optional PostgreSQL integration tests use disposable etl_test_* schemas:
$env:TEST_POSTGRES = '1'
python -m unittest discover -s tests
```

Tests cover resume, pagination, regional endpoints, ID collisions, filters,
salary units, secondary locations, immutable snapshots, transactional history,
repeat loads, outage fallback, and successful empty boards. PostgreSQL tests
require permission to create/drop their temporary schemas. Skills use keyword
matches and do not distinguish required from preferred or incidental mentions.

Reconcile the latest snapshot with its manifest and PostgreSQL rows:

```powershell
python verify_market.py --database
```

Use `--run-dir data/runs/<run-id>` for a specific snapshot, or omit `--database`
for local validation only. Example read-only analysis queries are in
[`sql/market_analysis.sql`](sql/market_analysis.sql).

### State normalization and replacement reloads

`transform/locations.py` recognizes explicit state names/codes and a curated city
lookup, including labels such as Boston, Mountain View, and San Francisco Bay
Area. Each enriched entry in `locations_json` records its `state_source`.
City lookups are inferences, not verified addresses. Ambiguous city names and
country-only remote listings retain an unknown state.

The main jobs table selects the first supported U.S. location with a known state.
For all supported states, use PostgreSQL's `vw_market_current_locations` or
`data/processed/job_locations.csv`. These contain one row per run/job/state.
Relate `job_id` to current jobs' `id` and count distinct job IDs per state.
Multi-state jobs appear in each applicable state, so state totals are not additive.

To back up and overwrite all existing company-market snapshots with one fresh
collection, rather than append another collection to history:

```powershell
python etl_job_market.py --refresh-directory --load --replace-market-data
```

Replacement happens in one transaction. If loading fails, previous rows remain.
Backups go to `data/backups/`; local dated run archives remain available.
An empty job snapshot is rejected. Failed boards appear in the new report, but
their previous observations are not retained in replacement mode.
