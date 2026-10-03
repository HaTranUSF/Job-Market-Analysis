"""Extract job postings from the USAJOBS API."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://data.usajobs.gov/api/search"
RESULTS_PER_PAGE = 100
REQUEST_TIMEOUT = (5, 45)
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
    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4),
    )
    return session


def fetch_jobs(
    user_agent: str,
    auth_key: str,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Extract all matching postings, paging each title query and deduplicating IDs."""
    if not user_agent or not auth_key:
        raise RuntimeError(
            "Set USAJOBS_USER_AGENT and USAJOBS_AUTH_KEY in the environment or .env."
        )

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
        raise RuntimeError(
            "USAJOBS returned no matching postings; refusing to write empty outputs."
        )

    raw = pd.DataFrame.from_records(records)
    raw = raw.loc[raw["id"].ne("")].drop_duplicates(subset="id", keep="last")
    LOG.info("Extracted %s unique postings", len(raw))
    return raw
