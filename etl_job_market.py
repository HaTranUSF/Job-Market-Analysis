"""USAJOBS ETL: fetch federal data jobs, normalize them, and load PostgreSQL."""

from __future__ import annotations

import argparse
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy.sql.sqltypes import Integer, Numeric as SQLNumeric
from requests.adapters import HTTPAdapter
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    bindparam,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Engine, URL
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
API_URL = "https://data.usajobs.gov/api/search"
RESULTS_PER_PAGE = 100
REQUEST_TIMEOUT = (5, 45)
DB_BATCH_SIZE = 1_000

ROLES = (
    "data analyst",
    "data scientist",
    "data engineer",
    "business analyst",
    "machine learning engineer",
    "analytics engineer",
    "data specialist",
    "research analyst",
    "business intelligence analyst",
    "data architect",
    "data warehouse engineer",
    "database administrator",
)

US_STATES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
}

EMPLOYMENT_TYPES = {
    "1": "Full-Time",
    "2": "Part-Time",
    "3": "Shift Work",
    "4": "Intermittent",
    "5": "Job Share",
    "6": "On-Call",
}

# Canonical skill values are written to a separate, normalized bridge table.
SKILL_PATTERNS = {
    "python": r"python",
    "r": r"r",
    "sql": r"sql",
    "java": r"java",
    "excel": r"excel",
    "tableau": r"tableau",
    "power bi": r"power\s+bi",
    "aws": r"aws",
    "azure": r"azure",
    "snowflake": r"snowflake",
    "spark": r"spark",
    "databricks": r"databricks",
    "machine learning": r"machine\s+learning",
    "data analysis": r"data\s+analysis",
    "statistics": r"statistics?",
    "regression": r"regression",
    "forecasting": r"forecasting",
    "data visualization": r"data\s+visuali[sz]ation",
    "reporting": r"reporting",
    "etl": r"etl",
}
SKILL_NAMES = tuple(SKILL_PATTERNS)
SKILL_REGEX = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        f"(?P<skill_{index}>{pattern})"
        for index, pattern in enumerate(SKILL_PATTERNS.values())
    )
    + r")(?!\w)",
    re.IGNORECASE,
)
POSTING_COLUMNS = [
    "id", "role", "title", "organization", "department", "city", "state",
    "description", "posted_date", "close_date", "job_grade", "salary_min",
    "salary_max", "employment_type", "is_remote",
]

metadata = MetaData()
POSTINGS_TABLE = Table(
    "job_skills",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("role", String(128)),
    Column("title", Text),
    Column("organization", Text),
    Column("department", Text),
    Column("city", Text),
    Column("state", Text),
    Column("description", Text),
    Column("posted_date", Date),
    Column("close_date", Date),
    Column("job_grade", String(64)),
    Column("salary_min", Numeric(14, 2)),
    Column("salary_max", Numeric(14, 2)),
    Column("employment_type", String(64)),
    Column("is_remote", Boolean),
)
POSTING_SKILLS_TABLE = Table(
    "job_posting_skills",
    metadata,
    Column("job_id", String(64), primary_key=True),
    Column("skill", String(64), primary_key=True),
)

LOG = logging.getLogger("job_market_etl")


def _first_mapping(value: Any) -> dict[str, Any]:
    """Return the first mapping from USAJOBS fields that may be lists or objects."""
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}


def _remote_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _employment_type(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = _first_mapping(value).get("Code")
    return EMPLOYMENT_TYPES.get(str(value), value) if value is not None else None


def build_session() -> requests.Session:
    """Create a keep-alive HTTP session with bounded retries for transient errors."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4))
    return session


def fetch_jobs(
    user_agent: str,
    auth_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Extract all matching postings, paging each title query and deduplicating IDs."""
    if not user_agent or not auth_key:
        raise RuntimeError("Set USAJOBS_USER_AGENT and USAJOBS_AUTH_KEY in the environment or .env.")

    http = session or build_session()
    headers = {"User-Agent": user_agent, "Authorization-Key": auth_key}
    records: list[dict[str, Any]] = []

    for role in ROLES:
        page = 1
        while True:
            response = http.get(
                API_URL,
                headers=headers,
                params={
                    "PositionTitle": role,
                    "ResultsPerPage": RESULTS_PER_PAGE,
                    "Page": page,
                    "Fields": "full",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            search_result = payload.get("SearchResult") or {}
            items = search_result.get("SearchResultItems") or []
            if not items:
                break

            for item in items:
                descriptor = item.get("MatchedObjectDescriptor") or {}
                remuneration = _first_mapping(descriptor.get("PositionRemuneration"))
                schedule = _first_mapping(descriptor.get("PositionSchedule"))
                grade = _first_mapping(descriptor.get("JobGrade"))
                detail = descriptor.get("UserArea") or {}
                detail = detail.get("Details") or {}
                records.append(
                    {
                        "id": str(item.get("MatchedObjectId", "")),
                        "role": role,
                        "title": descriptor.get("PositionTitle"),
                        "location": descriptor.get("PositionLocationDisplay"),
                        "organization": descriptor.get("OrganizationName"),
                        "department": descriptor.get("DepartmentName"),
                        "description": detail.get("JobSummary") or "",
                        "posted_date": descriptor.get("PublicationStartDate"),
                        "close_date": descriptor.get("ApplicationCloseDate"),
                        "job_grade": grade.get("Code"),
                        "salary_min": remuneration.get("MinimumRange"),
                        "salary_max": remuneration.get("MaximumRange"),
                        "employment_type": schedule.get("Code"),
                        "is_remote": _remote_flag(descriptor.get("RemoteIndicator")),
                    }
                )

            LOG.info("Fetched %s records for '%s' page %s", len(items), role, page)
            page += 1

    if not records:
        raise RuntimeError("USAJOBS returned no matching postings; refusing to write empty outputs.")

    raw = pd.DataFrame.from_records(records)
    raw = raw.loc[raw["id"].ne("")].drop_duplicates(subset="id", keep="last")
    LOG.info("Extracted %s unique postings", len(raw))
    return raw


def _classify_roles(titles: pd.Series) -> pd.Series:
    normalized = titles.fillna("").astype(str).str.lower()
    assigned = pd.Series(pd.NA, index=titles.index, dtype="string")
    # Ordered from specific categories to general ones, like the notebook's if/elif rules.
    rules = [
        (r"machine\s+learning|\bml\b|\bai\b|artificial intelligence", "machine learning engineer"),
        (r"warehouse|\betl\b", "data warehouse engineer"),
        (r"architect|data modeling", "data architect"),
        (r"analytics engineer", "analytics engineer"),
        (r"intelligence|\bbi\b", "business intelligence analyst"),
        (r"scientist|data science", "data scientist"),
        (r"engineer", "data engineer"),
        (r"administrator|\bdba\b|database", "database administrator"),
        (r"specialist", "data specialist"),
        (r"research", "research analyst"),
        (r"business.*analyst", "business analyst"),
        (r"analyst|analytics|data", "data analyst"),
    ]
    for pattern, role in rules:
        matches = normalized.str.contains(pattern, regex=True, na=False) & assigned.isna()
        assigned.loc[matches] = role

    excluded = normalized.str.contains(
        r"operator|mechanic|clerk|laundry|bindery|vending|driver|automotive",
        regex=True,
        na=False,
    )
    assigned = assigned.fillna("Other")
    assigned.loc[excluded] = "Other"
    return assigned


def _extract_skill_rows(postings: pd.DataFrame) -> pd.DataFrame:
    rows: list[tuple[str, str]] = []
    for job_id, description in postings[["id", "description"]].itertuples(index=False, name=None):
        text_value = str(description or "")
        canonical = {
            SKILL_NAMES[int(match.lastgroup.removeprefix("skill_"))]
            for match in SKILL_REGEX.finditer(text_value)
            if match.lastgroup is not None
        }
        rows.extend((str(job_id), skill) for skill in sorted(canonical))

    return pd.DataFrame(rows, columns=["job_id", "skill"])


def transform_jobs(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize USAJOBS records and produce a separate job-to-skill bridge dataset."""
    if raw.empty:
        raise ValueError("Input dataframe is empty; refusing to create an empty snapshot.")

    df = raw.copy()
    df["id"] = df["id"].astype("string").str.strip()
    df = df.loc[df["id"].notna() & df["id"].ne("")].drop_duplicates("id", keep="last").copy()
    df["role"] = _classify_roles(df["title"])
    df = df.loc[df["role"].ne("Other")].copy()

    df["salary_min"] = pd.to_numeric(df["salary_min"], errors="coerce")
    df["salary_max"] = pd.to_numeric(df["salary_max"], errors="coerce")
    for column in ("salary_min", "salary_max"):
        hourly = df[column].lt(500)
        df.loc[hourly, column] = df.loc[hourly, column] * 2_080

    for column in ("posted_date", "close_date"):
        df[column] = pd.to_datetime(df[column], errors="coerce", utc=True).dt.date

    df["employment_type"] = df["employment_type"].map(_employment_type)
    df["job_grade"] = df["job_grade"].map(
        lambda value: _first_mapping(value).get("Code") if isinstance(value, (list, dict)) else value
    )
    df["is_remote"] = df["is_remote"].map(_remote_flag).astype(bool)

    locations = df["location"].fillna("").astype(str).str.rsplit(",", n=1, expand=True)
    df["city"] = locations.iloc[:, 0].str.strip()
    if locations.shape[1] > 1:
        df["state"] = locations.iloc[:, 1].str.strip()
    else:
        df["state"] = pd.NA
    multiple = df["location"].fillna("").astype(str).str.strip().str.casefold().eq("multiple locations")
    df.loc[multiple, "city"] = "Various Cities"
    df.loc[multiple, "state"] = "Multiple Locations"
    df = df.loc[df["state"].isin(US_STATES | {"Multiple Locations"})].copy()

    for column in ("title", "organization", "department", "description", "city", "state", "job_grade", "employment_type"):
        df[column] = df[column].where(df[column].notna(), None)
    df["description"] = df["description"].fillna("")
    df = df[POSTING_COLUMNS].reset_index(drop=True)
    skill_rows = _extract_skill_rows(df)
    LOG.info("Transformed %s postings and matched %s job-skill pairs", len(df), len(skill_rows))
    return df, skill_rows


def _atomic_csv_write(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            frame.to_csv(temp_file, index=False)
        os.replace(temp_path, destination)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def write_csv_outputs(postings: pd.DataFrame, skills: pd.DataFrame, output_dir: Path) -> None:
    _atomic_csv_write(postings, output_dir / "job_skills.csv")
    _atomic_csv_write(skills, output_dir / "job_posting_skills.csv")
    LOG.info("Wrote CSV outputs to %s", output_dir)


def create_db_engine() -> Engine:
    required = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing database settings in environment/.env: {', '.join(missing)}")

    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1_800)


def _ensure_postings_columns(engine: Engine) -> None:
    """Create tables and add newly introduced nullable fields without replacing data."""
    metadata.create_all(engine)
    existing = {column["name"] for column in inspect(engine).get_columns("job_skills")}
    with engine.begin() as connection:
        for column in POSTINGS_TABLE.columns:
            if column.name not in existing:
                sql_type = column.type.compile(dialect=engine.dialect)
                connection.execute(
                    text(f'ALTER TABLE "job_skills" ADD COLUMN "{column.name}" {sql_type}')
                )
        connection.execute(text('CREATE INDEX IF NOT EXISTS "ix_job_skills_id" ON "job_skills" ("id")'))


def load_postings(engine: Engine, postings: pd.DataFrame, skills: pd.DataFrame) -> None:
    """Idempotently replace only IDs in this run, within one database transaction."""
    _ensure_postings_columns(engine)
    id_column = next(
        column for column in inspect(engine).get_columns("job_skills") if column["name"] == "id"
    )
    id_type = id_column["type"]
    numeric_id = isinstance(id_type, (Integer, SQLNumeric))
    ids = postings["id"].astype(str).drop_duplicates().tolist()
    if numeric_id:
        if not all(value.isdigit() for value in ids):
            raise ValueError("The existing job_skills.id column is numeric but a posting ID is not.")
        ids = [int(value) for value in ids]
    delete_postings = text('DELETE FROM "job_skills" WHERE "id" IN :ids').bindparams(
        bindparam("ids", expanding=True)
    )
    delete_skills = text('DELETE FROM "job_posting_skills" WHERE "job_id" IN :ids').bindparams(
        bindparam("ids", expanding=True)
    )

    with engine.begin() as connection:
        for offset in range(0, len(ids), DB_BATCH_SIZE):
            batch_ids = ids[offset : offset + DB_BATCH_SIZE]
            connection.execute(delete_postings, {"ids": batch_ids})
            connection.execute(delete_skills, {"ids": batch_ids})

        load_frame = postings.copy()
        if numeric_id:
            load_frame["id"] = load_frame["id"].astype("int64")
        load_frame.to_sql(
            "job_skills", con=connection, if_exists="append", index=False,
            chunksize=DB_BATCH_SIZE, method="multi",
        )
        if not skills.empty:
            skills.to_sql(
                "job_posting_skills", con=connection, if_exists="append", index=False,
                chunksize=DB_BATCH_SIZE, method="multi",
            )
    LOG.info("Loaded %s postings and %s skill links", len(postings), len(skills))


def run_pipeline(output_dir: Path, skip_load: bool = False, no_csv: bool = False) -> tuple[int, int]:
    load_dotenv(ROOT / ".env", override=False)
    raw = fetch_jobs(os.getenv("USAJOBS_USER_AGENT", ""), os.getenv("USAJOBS_AUTH_KEY", ""))
    postings, skills = transform_jobs(raw)
    if postings.empty:
        raise RuntimeError("No US data-role postings remain after transformation; refusing to load.")

    if not no_csv:
        write_csv_outputs(postings, skills, output_dir)
    if not skip_load:
        engine = create_db_engine()
        try:
            load_postings(engine, postings, skills)
        finally:
            engine.dispose()
    return len(postings), len(skills)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "processed",
        help="Directory for atomic CSV outputs (default: data/processed).",
    )
    parser.add_argument(
        "--skip-load",
        action="store_true",
        help="Only extract and write CSV files; do not connect to PostgreSQL.",
    )
    parser.add_argument("--no-csv", action="store_true", help="Do not write CSV outputs.")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    args = parse_args()
    try:
        job_count, skill_count = run_pipeline(args.output_dir, args.skip_load, args.no_csv)
    except Exception:
        LOG.exception("ETL failed")
        return 1
    LOG.info("ETL completed successfully: %s postings, %s skill links", job_count, skill_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
