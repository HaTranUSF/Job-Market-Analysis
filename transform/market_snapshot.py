"""Transform saved board responses into immutable, auditable run snapshots."""

from collections import Counter
import hashlib
from pathlib import Path

import pandas as pd

from ats_sources import ATS_COLUMNS, normalize_job, transform_ats
from pipeline_io import atomic_bytes, board_key, read_json, utc_now, write_csv, write_json


def build_snapshot(run_dir):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    if manifest["status"] in {"complete", "partial", "failed"}:
        return read_snapshot(run_dir)
    if manifest["status"] != "collected":
        raise ValueError("Finish collection before transforming this run")
    manifest["transform_sha256"] = hashlib.sha256(
        (Path(__file__).resolve().parents[1] / "ats_sources.py").read_bytes()
        + (Path(__file__).resolve().parents[1] / "job_fields.py").read_bytes()
        + Path(__file__).with_name("job_features.py").read_bytes()
        + Path(__file__).with_name("locations.py").read_bytes()
        + Path(__file__).read_bytes()).hexdigest()
    frames, skill_frames, report = [], [], []
    for board in manifest["boards"]:
        key = board_key(board)
        result = read_json(run_dir / "boards" / f"{key}.json")
        result.update(matched_postings=0, retained_postings=0)
        if result["status"] == "ok":
            try:
                raw = read_json(run_dir / "raw" / f"{key}.json.gz", compressed=True)
                records = [normalize_job(job, board, raw["collected_at"]) for job in raw["jobs"]]
                records = [r for r in records if r is not None]
                postings, skills = transform_ats(records, manifest["include_unknown_country"])
                result.update(matched_postings=len(records), retained_postings=len(postings))
                if not postings.empty:
                    postings.insert(0, "run_id", manifest["run_id"])
                    postings.insert(1, "board_key", key)
                    skills.insert(0, "run_id", manifest["run_id"])
                    frames.append(postings)
                    skill_frames.append(skills)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                # Exclude the whole board on parse errors so disappearance is never
                # inferred from an incompletely transformed response.
                result.update(status="transform_failed", error=f"{type(exc).__name__}: {exc}")
        report.append(result)
    postings = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["run_id", "board_key"] + ATS_COLUMNS)
    skills = pd.concat(skill_frames, ignore_index=True) if skill_frames else pd.DataFrame(columns=["run_id", "job_id", "skill"])
    if postings.id.duplicated().any():
        raise ValueError("Duplicate posting IDs across boards")
    if skills.duplicated(["job_id", "skill"]).any() or not set(skills.job_id).issubset(set(postings.id)):
        raise ValueError("Invalid posting-skill relationships")
    successful = sum(r["status"] == "ok" for r in report)
    summary = dict(run_id=manifest["run_id"], boards_attempted=len(report),
                   boards_successful=successful, boards_failed=len(report) - successful,
                   raw_postings=sum(r["raw_postings"] for r in report),
                   retained_postings=len(postings), skill_links=len(skills),
                   by_provider={provider: dict(
                       boards=sum(r["source"] == provider for r in report),
                       successful=sum(r["source"] == provider and r["status"] == "ok" for r in report),
                       postings=int(postings.source.eq(provider).sum())) for provider in manifest["providers"]},
                   missing_salary=int(postings.salary_min.isna().sum()),
                   unknown_country=int(postings.country.isna().sum()),
                   roles=dict(Counter(postings.role)))
    summary["coverage_complete"] = successful == len(report)
    summary["missing_posted_date"] = int(postings.posted_date.isna().sum())
    summary["missing_remote_status"] = int(postings.is_remote.isna().sum())
    summary["missing_state"] = int(postings.state.isna().sum())
    write_csv(run_dir / "job_skills.csv", postings)
    write_csv(run_dir / "job_posting_skills.csv", skills)
    write_json(run_dir / "board_report.json", report)
    write_json(run_dir / "summary.json", summary)
    manifest.update(status="complete" if successful == len(report) else "partial" if successful else "failed",
                    finished_at=utc_now(), summary=summary)
    write_json(run_dir / "manifest.json", manifest)
    return postings, skills, report, manifest


def read_snapshot(run_dir):
    run_dir = Path(run_dir)
    postings = pd.read_csv(run_dir / "job_skills.csv", dtype={"id": str, "source_job_id": str, "source_region": str})
    skills = pd.read_csv(run_dir / "job_posting_skills.csv", dtype=str)
    postings["source_region"] = postings.source_region.fillna("")
    for col in ("posted_date", "close_date"):
        postings[col] = pd.to_datetime(postings[col], errors="coerce", utc=True).dt.date
    postings["is_remote"] = postings.is_remote.map(lambda value: None if pd.isna(value) else str(value).lower() == "true")
    return postings, skills, read_json(run_dir / "board_report.json"), read_json(run_dir / "manifest.json")


def publish_snapshot(run_dir, output_dir):
    """Publish convenient CSV copies; latest.json points to the coherent run."""
    run_dir, output_dir = Path(run_dir), Path(output_dir)
    manifest = read_json(run_dir / "manifest.json")
    if manifest["status"] == "failed":
        return
    latest = output_dir / "latest.json"
    if latest.exists() and read_json(latest)["run_id"] > manifest["run_id"]:
        return
    for name in ("job_skills.csv", "job_posting_skills.csv", "board_report.json", "summary.json"):
        atomic_bytes(output_dir / name, (run_dir / name).read_bytes())
    postings, skills, _, _ = read_snapshot(run_dir)
    overview_columns = ["title", "organization", "role", "city", "state", "country",
                        "is_remote", "employment_type", "salary_min", "salary_max",
                        "salary_currency", "salary_period", "posted_date", "source", "job_url", "id"]
    overview = postings[overview_columns].copy()
    skill_names = skills.groupby("job_id")["skill"].agg(lambda values: ", ".join(sorted(set(values))))
    overview["skills"] = overview.id.map(skill_names).fillna("")
    for column in overview.select_dtypes(include="object"):
        overview[column] = overview[column].map(lambda value: " ".join(value.split()) if isinstance(value, str) else value)
    # A BOM helps Excel recognize Unicode when opening a CSV directly.
    atomic_bytes(output_dir / "jobs_overview.csv", overview.to_csv(index=False).encode("utf-8-sig"))
    import json
    location_rows = sorted({(row.run_id, row.id, loc["state"])
        for row in postings.itertuples()
        for loc in json.loads(row.locations_json)
        if loc.get("country") == "US" and loc.get("state")})
    write_csv(output_dir / "job_locations.csv", pd.DataFrame(location_rows, columns=["run_id", "job_id", "state"]))
    write_json(latest, dict(run_id=manifest["run_id"], run_dir=str(run_dir.resolve()),
                            status=manifest["status"], published_at=utc_now()))
