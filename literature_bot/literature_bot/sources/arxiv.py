"""arXiv adapter — preprints in physics, CS, math, stats, q-bio, econ. Free, no key.

https://info.arxiv.org/help/api/user-manual.html
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..models import Paper
from .base import get_text

BASE_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> List[Paper]:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": min(limit, 50),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    text = get_text(BASE_URL, params=params)
    if not text:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    papers: List[Paper] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title_el = entry.find(f"{ATOM_NS}title")
        summary_el = entry.find(f"{ATOM_NS}summary")
        published_el = entry.find(f"{ATOM_NS}published")
        id_el = entry.find(f"{ATOM_NS}id")

        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        if not title:
            continue
        abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else None
        year = None
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except ValueError:
                year = None
        if year_min and year and year < year_min:
            continue
        if year_max and year and year > year_max:
            continue

        authors = [
            (a.find(f"{ATOM_NS}name").text or "").strip()
            for a in entry.findall(f"{ATOM_NS}author")
            if a.find(f"{ATOM_NS}name") is not None
        ]

        arxiv_id = None
        pdf_url = None
        abs_url = id_el.text if id_el is not None else None
        if abs_url and "abs/" in abs_url:
            arxiv_id = abs_url.split("abs/")[-1]
            pdf_url = abs_url.replace("/abs/", "/pdf/")

        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                venue="arXiv preprint",
                abstract=abstract,
                doi=None,
                url=abs_url,
                pdf_url=pdf_url,
                citation_count=None,
                source="arXiv",
                extra_ids={"arxiv": arxiv_id} if arxiv_id else {},
            )
        )
    return papers
