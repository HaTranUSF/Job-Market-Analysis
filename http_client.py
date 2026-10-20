"""Shared HTTP retry policy for public company job boards."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REQUEST_TIMEOUT = (5, 45)


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
