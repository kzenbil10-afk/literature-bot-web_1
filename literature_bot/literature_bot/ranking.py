"""Score and sort the merged result set."""
from __future__ import annotations

import math
import re
from typing import List

from .models import Paper

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "is",
    "ve", "veya", "ile", "için", "bir", "bu", "da", "de", "mi", "mu", "üzerine",
}


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def score_papers(papers: List[Paper], query: str, weights=None) -> List[Paper]:
    """Assign a 0-1 relevance score to each paper and sort descending.

    weights: dict with keys term, citation, recency (default 0.5 / 0.3 / 0.2).
    """
    weights = weights or {"term": 0.5, "citation": 0.3, "recency": 0.2}
    query_terms = _tokenize(query)
    if not papers:
        return papers

    max_citations = max((p.citation_count or 0) for p in papers) or 1
    years = [p.year for p in papers if p.year]
    min_year, max_year = (min(years), max(years)) if years else (None, None)

    for p in papers:
        title_terms = _tokenize(p.title)
        abstract_terms = _tokenize(p.abstract or "")
        if query_terms:
            term_hits = len(query_terms & title_terms) * 2 + len(query_terms & abstract_terms)
            term_score = min(term_hits / (len(query_terms) * 2), 1.0)
        else:
            term_score = 0.5

        citation_score = math.log1p(p.citation_count or 0) / math.log1p(max_citations)

        if p.year and min_year is not None and max_year is not None and max_year > min_year:
            recency_score = (p.year - min_year) / (max_year - min_year)
        else:
            recency_score = 0.5

        p.score = round(
            weights["term"] * term_score
            + weights["citation"] * citation_score
            + weights["recency"] * recency_score,
            4,
        )

    return sorted(papers, key=lambda p: p.score, reverse=True)


def sort_papers(papers: List[Paper], by: str) -> List[Paper]:
    if by == "citations":
        return sorted(papers, key=lambda p: p.citation_count or 0, reverse=True)
    if by == "year":
        return sorted(papers, key=lambda p: p.year or 0, reverse=True)
    return sorted(papers, key=lambda p: p.score, reverse=True)
