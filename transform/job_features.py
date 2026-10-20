# Role classification, geographic constants, and description skill matching.

import re
import pandas as pd


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


def _classify_roles(titles: pd.Series) -> pd.Series:
    normalized = titles.fillna("").astype(str).str.lower()
    assigned = pd.Series(pd.NA, index=titles.index, dtype="string")
    # Match specific role categories before general ones.
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
