"""Clean and normalize raw USAJOBS records and derive skill links."""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

LOG = logging.getLogger("job_market_etl")


def _first_mapping(value: Any) -> dict[str, Any]:
    """Return the first mapping from values represented as lists or objects."""
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) else {}

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


def _employment_type(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = _first_mapping(value).get("Code")
    return EMPLOYMENT_TYPES.get(str(value), value) if value is not None else None


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
    for job_id, description in postings[["id", "description"]].itertuples(
        index=False, name=None
    ):
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
        lambda value: _first_mapping(value).get("Code")
        if isinstance(value, (list, dict))
        else value
    )
    df["is_remote"] = df["is_remote"].map(
        lambda value: value if isinstance(value, bool) else str(value).strip().lower() == "true"
    ).astype(bool)

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

    for column in (
        "title", "organization", "department", "description", "city", "state",
        "job_grade", "employment_type",
    ):
        df[column] = df[column].where(df[column].notna(), None)
    df["description"] = df["description"].fillna("")
    content_columns = [column for column in POSTING_COLUMNS if column != "id"]
    df = df[POSTING_COLUMNS].drop_duplicates(
        subset=content_columns,
        keep="last",
    ).reset_index(drop=True)
    skill_rows = _extract_skill_rows(df)
    LOG.info("Transformed %s postings and matched %s job-skill pairs", len(df), len(skill_rows))
    return df, skill_rows
