"""YÖK Ulusal Tez Merkezi adapter — Turkey's national thesis (Master's/PhD)
database (https://tez.yok.gov.tr), run by the Higher Education Council
(YÖK). No official search API exists, but the search results page renders
every result's metadata (author, year, university, thesis type, subject,
title) as a plain JSON object embedded directly in the HTML
(`const referenceData = {...}`), server-side -- no JavaScript execution
needed to read it, and no CAPTCHA was encountered as of 2026-09-24. There is
no robots.txt on this host restricting this either. This is a different
situation from Google Scholar, whose robots.txt explicitly disallows
crawling /scholar -- deliberately not adding a Scholar adapter for that
reason.

The site requires a session cookie (JSESSIONID) obtained from a plain GET of
the homepage before the search POST will return real results instead of a
redirect -- see `search()` below.

Trade-off, to keep this adapter simple and robust against markup changes:
only the Turkish title/metadata embedded in `referenceData` is parsed (not
the English title or the full abstract, both of which require either
scraping the surrounding HTML cards or an extra per-result AJAX call to
tezBilgiDetay.jsp). Good enough for search/discovery; a thesis's abstract
isn't fetched here the way it might be for --fetch-fulltext on other
sources.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

import requests

from ..models import Paper
from .base import USER_AGENT

HOME_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi/"
SEARCH_URL = "https://tez.yok.gov.tr/UlusalTezMerkezi/SearchTez"

_REFERENCE_DATA_RE = re.compile(r"const\s+referenceData\s*=\s*(\{.*?\});", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _parse_reference_data(html_text: str) -> dict:
    match = _REFERENCE_DATA_RE.search(html_text)
    if not match:
        return {}
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", match.group(1))
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        return {}


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    timeout: int = 40,
) -> List[Paper]:
    if not query or not query.strip():
        return []

    headers = {"User-Agent": USER_AGENT}
    try:
        session = requests.Session()
        # A session cookie from a plain GET is required first -- posting
        # straight to SearchTez without one gets redirected (302) instead
        # of returning results.
        session.get(HOME_URL, headers=headers, timeout=timeout)
        resp = session.post(
            SEARCH_URL,
            headers=headers,
            data={"izin": "0", "tur": "0", "neden": query, "islem": "1"},
            timeout=timeout,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    reference_data = _parse_reference_data(resp.text)
    if not reference_data:
        return []

    papers: List[Paper] = []
    # referenceData's keys are "0", "1", "2", ... in result order (most
    # relevant first per YÖK's own ranking) -- sort numerically and take the
    # first `limit` after year filtering, rather than relying on dict order.
    for key in sorted(reference_data.keys(), key=lambda k: int(k) if k.isdigit() else 0):
        entry = reference_data.get(key) or {}
        meta = entry.get("meta") or {}
        title = (meta.get("title") or "").strip()
        if not title:
            continue

        year_val = None
        year_raw = (meta.get("year") or "").strip()
        if year_raw.isdigit():
            year_val = int(year_raw)
        if year_min and year_val and year_val < year_min:
            continue
        if year_max and year_val and year_val > year_max:
            continue

        author = (meta.get("author") or "").strip()
        university = (meta.get("yer") or "").strip().rstrip("/").strip()
        thesis_type = (meta.get("type") or "").strip()
        subject = (meta.get("subject") or "").strip()
        venue_parts = [p for p in (university, thesis_type) if p]
        venue = " — ".join(venue_parts) if venue_parts else None

        papers.append(
            Paper(
                title=title,
                authors=[author] if author else [],
                year=year_val,
                venue=venue,
                abstract=None,
                doi=None,
                # No stable per-thesis deep link is exposed server-side (the
                # detail view is loaded via an AJAX call keyed by opaque,
                # per-session record ids) -- link to the search portal
                # itself rather than a broken/session-bound URL.
                url=HOME_URL,
                pdf_url=None,
                source="yok_tez",
                extra_ids={"yok_subject": subject} if subject else {},
            )
        )
        if len(papers) >= limit:
            break

    return papers
