"""Semantic Scholar adapter — strong abstract + citation-graph coverage.

Free tier works without a key but is tightly rate-limited; pass an API key
(https://www.semanticscholar.org/product/api#api-key-form) for reliable use.
"""
from __future__ import annotations

from typing import List, Optional

from ..models import Paper
from .base import get_json

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,authors,year,venue,citationCount,externalIds,openAccessPdf,url"


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    api_key: Optional[str] = None,
) -> List[Paper]:
    params = {
        "query": query,
        "limit": min(limit, 100),
        "fields": FIELDS,
    }
    if year_min or year_max:
        params["year"] = f"{year_min or ''}-{year_max or ''}"

    headers = {"x-api-key": api_key} if api_key else None
    data = get_json(BASE_URL, params=params, headers=headers)
    if not data or "data" not in data:
        return []

    papers: List[Paper] = []
    for item in data["data"]:
        authors = [a.get("name", "") for a in item.get("authors", []) if a.get("name")]
        ext = item.get("externalIds") or {}
        oa = item.get("openAccessPdf") or {}
        papers.append(
            Paper(
                title=item.get("title") or "",
                authors=authors,
                year=item.get("year"),
                venue=item.get("venue"),
                abstract=item.get("abstract"),
                doi=ext.get("DOI"),
                url=item.get("url"),
                pdf_url=oa.get("url"),
                citation_count=item.get("citationCount"),
                source="Semantic Scholar",
                extra_ids={k: v for k, v in ext.items() if k != "DOI"},
            )
        )
    return papers
