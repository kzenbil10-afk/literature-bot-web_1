"""Shared HTTP helpers for all source adapters: retries, backoff, rate-limit handling."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

USER_AGENT = "literature-bot/1.0 (https://github.com/; mailto:research-bot@example.com)"


class SourceError(Exception):
    """Raised when a source cannot be queried (network error, bad response, etc.)."""


def get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 25,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """GET a URL and parse JSON, with exponential backoff on 429/5xx.

    Returns None (instead of raising) when the source is unreachable after
    retries, so a single failing API never aborts the whole search.
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    delay = 1.5
    last_status = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
        except requests.RequestException:
            time.sleep(delay)
            delay *= 2
            continue

        last_status = resp.status_code
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            time.sleep(min(wait, 20))
            delay *= 2
            continue
        # 4xx other than 429: not retryable
        return None

    return None


def get_text(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 25,
    max_retries: int = 3,
) -> Optional[str]:
    """GET a URL and return raw text (for XML APIs like arXiv / PubMed)."""
    hdrs = {"User-Agent": USER_AGENT}
    delay = 1.5
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
        except requests.RequestException:
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 200:
            return resp.text
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(delay)
            delay *= 2
            continue
        return None
    return None
