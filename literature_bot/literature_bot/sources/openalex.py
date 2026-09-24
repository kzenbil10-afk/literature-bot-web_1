"""OpenAlex adapter — broad multidisciplinary coverage, free, no API key required.

https://docs.openalex.org/
"""
from __future__ import annotations

from typing import List, Optional

from ..models import Paper
from .base import get_json

BASE_URL = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the plain text."""
    if not inverted_index:
        return None
    positions: List[tuple] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    email: Optional[str] = None,
) -> List[Paper]:
    params = {
        "search": query,
        "per-page": min(limit, 50),
        "sort": "relevance_score:desc",
    }
    filters = []
    if year_min:
        filters.append(f"from_publication_date:{year_min}-01-01")
    if year_max:
        filters.append(f"to_publication_date:{year_max}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if email:
        params["mailto"] = email

    data = get_json(BASE_URL, params=params)
    if not data or "results" not in data:
        return []

    papers: List[Paper] = []
    for item in data["results"]:
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in item.get("authorships", [])
            if a.get("author", {}).get("display_name")
        ]
        doi = item.get("doi")
        if doi:
            doi = doi.replace("https://doi.org/", "")
        primary = item.get("primary_location") or {}
        source_info = primary.get("source") or {}
        oa = item.get("open_access") or {}
        pdf_url = primary.get("pdf_url") or oa.get("oa_url")

        papers.append(
            Paper(
                title=item.get("display_name") or item.get("title") or "",
                authors=authors,
                year=item.get("publication_year"),
                venue=source_info.get("display_name"),
                abstract=_reconstruct_abstract(item.get("abstract_inverted_index")),
                doi=doi,
                url=primary.get("landing_page_url") or item.get("id"),
                pdf_url=pdf_url,
                citation_count=item.get("cited_by_count"),
                source="OpenAlex",
                extra_ids={"openalex": item.get("id")},
            )
        )
    return papers
