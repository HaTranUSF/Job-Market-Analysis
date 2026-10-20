"""Restartable, bounded parallel collection of every board in a frozen directory."""

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from ats_sources import PROVIDERS, fetch_board, read_directory, select_boards
from http_client import build_session
from pipeline_io import atomic_bytes, board_key, collection_identity, read_json, utc_now, write_json

LOG = logging.getLogger("job_market_etl")


class RequestGate:
    """Space all requests across workers; retries are handled by urllib3."""
    def __init__(self, interval=0.25):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_request = 0

    def wait(self):
        with self.lock:
            wait = max(0, self.next_request - time.monotonic())
            self.next_request = time.monotonic() + wait + self.interval
        if wait:
            time.sleep(wait)


class GatedSession:
    def __init__(self, session, gate):
        self.session, self.gate = session, gate

    def get(self, *args, **kwargs):
        self.gate.wait()
        return self.session.get(*args, **kwargs)


def new_run(directory_path, runs_dir, providers=PROVIDERS, board_limit=None,
            refresh=False, active_only=False, include_unknown_country=False):
    with build_session() as session:
        rows = read_directory(directory_path, refresh, session)
    statuses = ("ok",) if active_only else ("ok", "dead", "unconfirmed")
    boards = select_boards(rows, providers, board_limit, statuses=statuses)
    if not boards:
        raise ValueError("The directory has no eligible boards")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot = Path(directory_path).read_bytes()
    atomic_bytes(run_dir / "directory.jsonl", snapshot)
    metadata_path = Path(directory_path).with_suffix(".metadata.json")
    if metadata_path.exists():
        atomic_bytes(run_dir / "directory.metadata.json", metadata_path.read_bytes())
    manifest = dict(run_id=run_id, collection_id=run_id, started_at=utc_now(), status="collecting",
                    directory_sha256=hashlib.sha256(snapshot).hexdigest(),
                    providers=list(providers), boards=boards,
                    include_unknown_country=include_unknown_country,
                    active_only=active_only, board_limit=board_limit,
                    pipeline_version=2)
    write_json(run_dir / "manifest.json", manifest)
    return run_dir


def reprocess_run(source_dir, runs_dir):
    """Derive a new snapshot from saved responses, preserving the original."""
    source_dir = Path(source_dir)
    original = read_json(source_dir / "manifest.json")
    if original["status"] not in {"collected", "complete", "partial", "failed"}:
        raise ValueError("Finish collecting the source run before reprocessing")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in ("directory.jsonl", "directory.metadata.json"):
        if (source_dir / name).exists():
            atomic_bytes(run_dir / name, (source_dir / name).read_bytes())
    for board in original["boards"]:
        key = board_key(board)
        checkpoint = source_dir / "boards" / f"{key}.json"
        atomic_bytes(run_dir / "boards" / checkpoint.name, checkpoint.read_bytes())
        raw = source_dir / "raw" / f"{key}.json.gz"
        if raw.exists():
            atomic_bytes(run_dir / "raw" / raw.name, raw.read_bytes())
    manifest = {k: v for k, v in original.items() if k not in {"summary", "finished_at"}}
    manifest.update(run_id=run_id, collection_id=collection_identity(original, source_dir.parent),
                    source_run_id=original["run_id"], status="collected", reprocessed_at=utc_now())
    write_json(run_dir / "manifest.json", manifest)
    return run_dir


def collect_one(board, run_dir, gate):
    key = board_key(board)
    result = dict(board_key=key, source=board["provider"], source_board=board["slug"],
                  source_region=board.get("region") or "", organization=board.get("name"),
                  directory_status=board.get("status"), collected_at=utc_now())
    try:
        with build_session() as session:
            session.headers["User-Agent"] = "Job-Market-Analysis/2.0 (public job-board ETL)"
            jobs = fetch_board(board, GatedSession(session, gate))
        write_json(run_dir / "raw" / f"{key}.json.gz", dict(board=board, jobs=jobs,
                   collected_at=result["collected_at"]), compressed=True)
        result.update(status="ok", raw_postings=len(jobs), error=None)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        result.update(status="failed", raw_postings=0, error=f"{type(exc).__name__}: {exc}")
    result["finished_at"] = utc_now()
    write_json(run_dir / "boards" / f"{key}.json", result)
    return result


def collect_run(run_dir, workers=4, retry_failed=False, interval=0.25):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    if manifest["status"] in {"complete", "partial", "failed"} and not retry_failed:
        LOG.info("Reusing completed collection %s", manifest["run_id"])
        return manifest
    if workers < 1 or workers > 16:
        raise ValueError("workers must be between 1 and 16")
    pending, results = [], []
    for board in manifest["boards"]:
        path = run_dir / "boards" / f"{board_key(board)}.json"
        result = read_json(path) if path.exists() else None
        raw_exists = (run_dir / "raw" / f"{board_key(board)}.json.gz").exists()
        if result and ((result["status"] == "ok" and raw_exists) or
                       (result["status"] == "failed" and not retry_failed)):
            results.append(result)
        else:
            pending.append(board)
    if retry_failed and manifest["status"] in {"complete", "partial", "failed"}:
        raise ValueError("Finalized runs are immutable. Start a new run to retry unavailable boards.")
    manifest["status"] = "collecting"
    write_json(run_dir / "manifest.json", manifest)
    LOG.info("Run %s: %s boards; %s checkpointed; %s pending", manifest["run_id"],
             len(manifest["boards"]), len(results), len(pending))
    gate = RequestGate(interval)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(collect_one, board, run_dir, gate) for board in pending]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result["status"] != "ok":
                LOG.warning("%s/%s: %s", result["source"], result["source_board"], result["error"])
            if len(results) % 25 == 0 or len(results) == len(manifest["boards"]):
                LOG.info("Collection progress %s/%s boards (%s failed)", len(results),
                         len(manifest["boards"]), sum(r["status"] != "ok" for r in results))
    manifest.update(status="collected", collection_finished_at=utc_now())
    write_json(run_dir / "manifest.json", manifest)
    return manifest
