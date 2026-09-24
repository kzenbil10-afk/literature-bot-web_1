"""Crossref adapter — DOI registry covering most journals/conferences, free, no key.

https://api.crossref.org/swagger-ui/index.html
"""
from __future__ import annotations

import html
import re
from typing import List, Optional

from ..models import Paper
from .base import get_json

BASE_URL = "https://api.crossref.org/works"


def _strip_jats(text: Optional[str]) -> Optional[str]:
    """Crossref abstracts are JATS-tagged XML fragments (<jats:p>...</jats:p>), and some
    publishers submit them with entities already HTML-escaped once (or twice), e.g.
    "&amp;lt;p&amp;gt;...". Unescape before *and* after stripping tags so both cases end
    up as clean plain text instead of literal "&lt;p&gt;" junk in the report."""
    if not text:
        return None
    unescaped = html.unescape(html.unescape(text))
    stripped = re.sub(r"<[^>]+>", " ", unescaped)
    cleaned = re.sub(r"\s+", " ", stripped).strip()
    return cleaned or None


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    email: Optional[str] = None,
) -> List[Paper]:
    params = {
        "query": query,
        "rows": min(limit, 50),
        "select": "DOI,title,author,issued,container-title,abstract,is-referenced-by-count,URL,type",
        "sort": "relevance",
    }
    filters = []
    if year_min:
        filters.append(f"from-pub-date:{year_min}-01-01")
    if year_max:
        filters.append(f"until-pub-date:{year_max}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if email:
        params["mailto"] = email

    data = get_json(BASE_URL, params=params)
    if not data or "message" not in data:
        return []

    papers: List[Paper] = []
    for item in data["message"].get("items", []):
        titles = item.get("title") or []
        if not titles:
            continue
        authors = []
        for a in item.get("author", []) or []:
            name = " ".join(p for p in [a.get("given"), a.get("family")] if p)
            if name:
                authors.append(name)
        year = None
        issued = (item.get("issued") or {}).get("date-parts") or []
        if issued and issued[0]:
            year = issued[0][0]
        venue_list = item.get("container-title") or []

        papers.append(
            Paper(
                title=titles[0],
                authors=authors,
                year=year,
                venue=venue_list[0] if venue_list else None,
                abstract=_strip_jats(item.get("abstract")),
                doi=item.get("DOI"),
                url=item.get("URL"),
                citation_count=item.get("is-referenced-by-count"),
                source="Crossref",
            )
        )
    return papers
