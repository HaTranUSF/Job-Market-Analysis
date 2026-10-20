"""Atomic local artifacts shared by collection, transformation, and loading."""

import gzip
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def board_key(board):
    """Stable board identity shared by collection and transformation."""
    return hashlib.sha256(json.dumps([board["provider"], board["slug"], board.get("region")],
                                    ensure_ascii=False).encode()).hexdigest()


def collection_identity(manifest, runs_dir):
    """Follow reprocessing lineage to the original API collection."""
    seen = set()
    current = manifest
    while True:
        if current.get("collection_id"):
            return current["collection_id"]
        key = current["run_id"]
        if key in seen:
            raise ValueError("Circular collection lineage")
        seen.add(key)
        parent = current.get("source_run_id")
        if not parent:
            return key
        path = Path(runs_dir) / parent / "manifest.json"
        if not path.exists():
            return parent
        current = read_json(path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_bytes(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value, compressed=False):
    content = json.dumps(value, ensure_ascii=False, indent=None if compressed else 2).encode("utf-8")
    atomic_bytes(Path(path), gzip.compress(content) if compressed else content)


def read_json(path, compressed=False):
    content = Path(path).read_bytes()
    return json.loads(gzip.decompress(content) if compressed else content)


def write_csv(path, frame):
    atomic_bytes(Path(path), frame.to_csv(index=False).encode("utf-8"))


@contextmanager
def run_lock(run_dir):
    """OS-managed lock releases even when a collector is interrupted."""
    path = Path(run_dir) / ".lock"
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another process is already using this run directory") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
