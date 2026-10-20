"""Public ATS directory discovery, extraction, and normalized data-role postings."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from http_client import REQUEST_TIMEOUT, build_session
from job_fields import POSTING_COLUMNS
from transform.job_features import US_STATES, _classify_roles, _extract_skill_rows
from transform.locations import enrich_locations, resolve
from pipeline_io import atomic_bytes, write_json

DIRECTORY_URL = "https://raw.githubusercontent.com/moonie0201/ats-directory/main/companies.jsonl"
PROVIDERS = ("greenhouse", "lever", "ashby")
LOG = logging.getLogger("job_market_etl")
STATE_CODES = dict(zip(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split(),
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia".split("|"),
))
DATA_TITLE = re.compile(
    r"\bdata\s+(?:analyst|scientist|engineer|architect|specialist|intern|manager|science|engineering|analysis|warehouse|model|operations|governance)\b"
    r"|\banalytics\b|\bbusiness\s+(?:intelligence|analyst)\b"
    r"|\bmachine\s+learning\b|\bdatabase\b|\bresearch\s+analyst\b|\bETL\b|\bML\s+engineer\b", re.I)


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = _TextParser()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


def read_directory(path: Path, refresh=False, session=None):
    """Cache the original directory plus retrieval time and content fingerprint."""
    if refresh or not path.exists():
        if session is None:
            with build_session() as http:
                return read_directory(path, refresh, http)
        response = session.get(DIRECTORY_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        content = response.text
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        if not rows or not any(r.get("provider") in PROVIDERS for r in rows):
            raise ValueError("Directory contains no supported boards")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(path, content.encode("utf-8"))
        write_json(path.with_suffix(".metadata.json"), {
            "url": DIRECTORY_URL, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(content.encode()).hexdigest(), "license": "CC0-1.0",
        })
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_boards(rows, providers=PROVIDERS, limit=None, statuses=("ok",)):
    selected, seen = [], set()
    for provider in providers:
        count = 0
        for row in rows:
            key = (provider, row.get("slug"), row.get("region"))
            if row.get("provider") != provider or row.get("status") not in statuses or not row.get("slug") or key in seen:
                continue
            if limit is not None and count >= limit:
                break
            seen.add(key)
            selected.append(row)
            count += 1
    return selected


def fetch_board(board, session):
    provider, slug = board["provider"], quote(board["slug"], safe="")
    if provider == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        params = {"content": "true"}
    elif provider == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        params = {"includeCompensation": "true"}
    elif provider == "lever":
        host = "api.eu.lever.co" if board.get("region") == "eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{slug}"
        params = {"mode": "json", "limit": 100, "skip": 0}
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    records = []
    seen_pages = set()
    while True:
        response = session.get(url, params=params.copy(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        jobs = payload if provider == "lever" else payload["jobs"]
        if not isinstance(jobs, list):
            raise ValueError("Expected a list of jobs")
        if not all(isinstance(job, dict) for job in jobs):
            raise ValueError("Expected job objects")
        fingerprint = hashlib.sha256(json.dumps(jobs, sort_keys=True).encode()).hexdigest()
        if jobs and fingerprint in seen_pages:
            raise ValueError("API repeated a page; refusing to treat a truncated board as complete")
        seen_pages.add(fingerprint)
        records.extend(jobs)
        if provider != "lever" or len(jobs) < params["limit"]:
            return records
        params["skip"] += params["limit"]


def normalize_job(job, board, collected_at):
    provider = board["provider"]
    record = dict.fromkeys(POSTING_COLUMNS)
    record.update(source=provider, source_board=board["slug"], collected_at=collected_at,
                  source_region=board.get("region") or "",
                  organization=board.get("name") or board["slug"])
    salary = {}
    if provider == "greenhouse":
        if "internal_job_id" in job and job["internal_job_id"] is None:
            return None  # Greenhouse prospect posts are not job vacancies.
        record.update(title=job.get("title"), description=plain_text(job.get("content")),
                      location=(job.get("location") or {}).get("name"),
                      department="; ".join(d["name"] for d in job.get("departments", [])),
                      job_url=job.get("absolute_url"), apply_url=job.get("absolute_url"),
                      source_updated_at=job.get("updated_at"),
                      posted_date=job.get("first_published"), close_date=job.get("application_deadline"))
        locations = [dict(location=record["location"])]
        locations += [dict(location=o.get("location") or o.get("name")) for o in job.get("offices") or []]
    elif provider == "lever":
        categories = job.get("categories") or {}
        sections = [job.get("descriptionPlain") or plain_text(job.get("description"))]
        sections += [plain_text(item.get("text")) + " " + plain_text(item.get("content")) for item in job.get("lists", [])]
        sections.append(job.get("additionalPlain") or plain_text(job.get("additional")))
        record.update(title=job.get("text"), description=" ".join(filter(None, sections)),
                      location=categories.get("location"), department=categories.get("department") or categories.get("team"),
                      employment_type=categories.get("commitment"), job_url=job.get("hostedUrl"),
                      apply_url=job.get("applyUrl"), workplace_type=job.get("workplaceType"),
                      country=job.get("country"))
        salary = job.get("salaryRange") or {}
        locations = [dict(location=loc, country=job.get("country") if loc == record["location"] else None)
                     for loc in categories.get("allLocations") or [record["location"]]]
    else:
        if job.get("isListed") is False:
            return None
        record.update(title=job.get("title"), description=job.get("descriptionPlain") or plain_text(job.get("descriptionHtml")),
                      location=job.get("location"), department=job.get("department"),
                      employment_type=job.get("employmentType"), posted_date=job.get("publishedAt"),
                      job_url=job.get("jobUrl"), apply_url=job.get("applyUrl"), workplace_type=job.get("workplaceType"))
        address = (job.get("address") or {}).get("postalAddress") or {}
        record.update(city=address.get("addressLocality"), state=address.get("addressRegion"), country=address.get("addressCountry"))
        locations = [dict(location=record["location"], city=record["city"], state=record["state"], country=record["country"])]
        locations += [dict(location=s.get("location"), city=(s.get("address") or {}).get("addressLocality"),
                           state=(s.get("address") or {}).get("addressRegion"),
                           country=(s.get("address") or {}).get("addressCountry")) for s in job.get("secondaryLocations") or []]
        components = (job.get("compensation") or {}).get("summaryComponents") or []
        salaries = [c for c in components if c.get("compensationType") == "Salary"]
        if len(salaries) == 1:
            s = salaries[0]
            salary = dict(min=s.get("minValue"), max=s.get("maxValue"), currency=s.get("currencyCode"), interval=s.get("interval"))
    if not DATA_TITLE.search(record.get("title") or ""):
        return None
    source_id = job.get("id") or record.get("job_url")
    if not source_id:
        raise ValueError("Posting has neither an ID nor a job URL")
    identity = json.dumps([provider, board["slug"], board.get("region"), str(source_id)])
    record["id"] = provider + ":" + hashlib.sha256(identity.encode()).hexdigest()[:48]
    record["source_job_id"] = str(source_id)
    record["locations_json"] = json.dumps(locations, ensure_ascii=False)
    record["salary_min"], record["salary_max"] = salary.get("min"), salary.get("max")
    record["salary_currency"], record["salary_period"] = salary.get("currency"), salary.get("interval")
    record["is_remote"] = job.get("isRemote") if "isRemote" in job else (
        str(record.get("workplace_type")).lower() == "remote" if record.get("workplace_type") else None)
    return record


ATS_COLUMNS = POSTING_COLUMNS + ["source_region", "locations_json", "salary_period_raw",
                                  "salary_min_annual_usd", "salary_max_annual_usd", "content_hash"]


def resolve_location(value):
    return resolve(value, STATE_CODES)[:3]


def transform_ats(records, include_unknown_country=False):
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=ATS_COLUMNS), pd.DataFrame(columns=["job_id", "skill"])
    for column in ATS_COLUMNS:
        if column not in frame:
            frame[column] = None
    frame["role"] = _classify_roles(frame["title"])
    frame = frame.loc[frame.role.ne("Other")].copy()
    for idx, row in frame.iterrows():
        locations = json.loads(row["locations_json"]) if row.get("locations_json") else [row.to_dict()]
        locations = enrich_locations(locations, STATE_CODES)
        frame.loc[idx, "locations_json"] = json.dumps(locations, ensure_ascii=False)
        resolved = [resolve_location(loc) for loc in locations]
        city, state, country = next((loc for loc in resolved if loc[2] == "US" and loc[1]),
            next((loc for loc in resolved if loc[2] == "US"), resolved[0] if resolved else (None, None, None)))
        # If the primary country is unknown but another location is known foreign,
        # preserve that evidence rather than calling the posting US-eligible.
        frame.loc[idx, ["city", "state", "country"]] = [city, state, country or None]
    keep = frame.country.eq("US")
    if include_unknown_country:
        keep |= frame.country.isna()
    frame = frame.loc[keep].copy()
    for col in ("posted_date", "close_date"):
        frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce", format="mixed").dt.date
    for col in ("salary_min", "salary_max"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame[col] = frame[col].where(frame[col].map(lambda value: math.isfinite(value) and value >= 0))
    reversed_range = frame.salary_min.gt(frame.salary_max)
    frame.loc[reversed_range, ["salary_min", "salary_max"]] = float("nan")
    frame["employment_type"] = frame.employment_type.replace({"FullTime": "Full-Time", "PartTime": "Part-Time", "full-time": "Full-Time", "part-time": "Part-Time", "Intern": "Internship"})
    frame["salary_period_raw"] = frame.salary_period
    periods = {"year": "year", "annual": "year", "1 YEAR": "year", "per-year-salary": "year",
               "hour": "hour", "hourly": "hour", "1 HOUR": "hour", "per-hour-wage": "hour",
               "month": "month", "1 MONTH": "month", "per-month-salary": "month",
               "week": "week", "1 WEEK": "week", "per-week-salary": "week",
               "day": "day", "1 DAY": "day", "per-day-wage": "day"}
    frame["salary_period"] = frame.salary_period.map(lambda value: periods.get(value, value))
    frame["salary_currency"] = frame.salary_currency.map(lambda value: value.upper() if isinstance(value, str) else None)
    factors = frame.salary_period.map({"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080})
    for bound in ("min", "max"):
        frame[f"salary_{bound}_annual_usd"] = (frame[f"salary_{bound}"] * factors).where(frame.salary_currency.eq("USD"))
    frame["content_hash"] = frame.apply(lambda row: hashlib.sha256(json.dumps(
        {key: (None if pd.isna(row[key]) else format(float(row[key]), ".12g")
               if key in {"salary_min", "salary_max", "salary_min_annual_usd", "salary_max_annual_usd"}
               else str(row[key])) for key in ATS_COLUMNS
         if key not in {"content_hash", "collected_at", "source_updated_at"}}, sort_keys=True).encode()).hexdigest(), axis=1) if not frame.empty else None
    frame = frame.reindex(columns=ATS_COLUMNS).drop_duplicates("id").reset_index(drop=True)
    return frame, _extract_skill_rows(frame)


def fetch_ats_jobs(directory_path, providers=PROVIDERS, board_limit=None, refresh=False,
                   report_path=None, include_unknown_country=False, delay=0.2):
    records, report = [], []
    with build_session() as session:
        boards = select_boards(read_directory(directory_path, refresh, session), providers, board_limit)
        if not boards:
            raise RuntimeError("No eligible boards in the directory")
        collected_at = datetime.now(timezone.utc).isoformat()
        for board in boards:
            result = dict(provider=board["provider"], slug=board["slug"], region=board.get("region"), collected_at=collected_at)
            try:
                jobs = fetch_board(board, session)
                normalized = [normalize_job(job, board, collected_at) for job in jobs]
                records.extend(r for r in normalized if r is not None)
                result.update(status="ok", postings=len(jobs))
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                result.update(status="failed", error=str(exc))
                LOG.warning("Failed %s/%s: %s", board["provider"], board["slug"], exc)
            report.append(result)
            LOG.info("Board %s/%s: %s", board["provider"], board["slug"], result["status"])
            time.sleep(delay)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    postings, skills = transform_ats(records, include_unknown_country)
    if postings.empty:
        raise RuntimeError("No matching US data-role postings collected; existing CSV outputs were preserved. See board report or increase --board-limit.")
    return postings, skills
