"""Score and sort the merged result set."""
from __future__ import annotations

import math
import re
from typing import List

from .models import Paper

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "is",
    "ve", "veya", "ile", "için", "bir", "bu", "şu", "o", "da", "de", "ta", "te",
    "ki", "mi", "mu", "mı", "mü", "üzerine",
}

# Turkish possessive/case suffixes commonly glued onto a proper noun after an
# apostrophe (e.g. "Türkiye'de", "COVID-19'un"). These carry no topical
# meaning on their own; without stripping them first, the general word-split
# below turns them into throwaway standalone tokens (e.g. "de") that can
# spuriously match unrelated documents and dilute the real query terms.
_TR_APOSTROPHE_SUFFIXES = sorted(
    {
        "de", "da", "te", "ta", "nin", "nın", "nun", "nün", "in", "ın", "un", "ün",
        "ye", "ya", "e", "a", "den", "dan", "ten", "tan", "yi", "yı", "yu", "yü",
        "i", "ı", "u", "ü", "la", "le", "nda", "nde", "ndan", "nden", "yle", "yla",
        "nı", "ni", "nu", "nü",
    },
    key=len,
    reverse=True,
)
_APOSTROPHE_SUFFIX_RE = re.compile(
    r"'(?:" + "|".join(_TR_APOSTROPHE_SUFFIXES) + r")\b", re.IGNORECASE
)


def _tokenize(text: str) -> set:
    text = _APOSTROPHE_SUFFIX_RE.sub("", text or "")
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", text.lower())
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

        # Citation count and recency may only ever break ties *among*
        # topically relevant papers. They must never be able to push a
        # paper that has no real overlap with the query above -- or even
        # anywhere near -- one that does, just because it happens to be
        # well-cited or recent (this was the cause of unrelated-topic
        # papers, e.g. logistics results for an unemployment query,
        # outranking genuine matches). So term relevance *gates* the
        # secondary signals multiplicatively instead of simply being added
        # to them: zero term overlap -> zero score, full stop.
        secondary = weights["citation"] * citation_score + weights["recency"] * recency_score
        if query_terms:
            p.score = round(weights["term"] * term_score + secondary * term_score, 4)
        else:
            p.score = round(weights["term"] * term_score + secondary, 4)

    return sorted(papers, key=lambda p: p.score, reverse=True)


def sort_papers(papers: List[Paper], by: str) -> List[Paper]:
    if by == "citations":
        return sorted(papers, key=lambda p: p.citation_count or 0, reverse=True)
    if by == "year":
        return sorted(papers, key=lambda p: p.year or 0, reverse=True)
    return sorted(papers, key=lambda p: p.score, reverse=True)
