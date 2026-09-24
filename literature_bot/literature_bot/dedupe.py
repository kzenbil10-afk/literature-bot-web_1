"""Cross-source deduplication: the same paper often comes back from OpenAlex,
Crossref, Semantic Scholar *and* arXiv at once. We merge those into one record
instead of showing the user four near-identical entries."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

from .models import Paper


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize_doi(doi: str) -> str:
    return doi.lower().strip().replace("https://doi.org/", "").rstrip("/")


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def deduplicate(papers: List[Paper], title_threshold: float = 0.9) -> List[Paper]:
    """Merge duplicate records. DOI match is authoritative; otherwise fall back
    to normalized-title similarity guarded by matching (or missing) year."""
    merged: List[Paper] = []
    doi_index: dict = {}
    norm_titles: List[str] = []

    for p in papers:
        norm_title = _normalize_title(p.title)
        doi_key = _normalize_doi(p.doi) if p.doi else None

        match_idx = None
        if doi_key and doi_key in doi_index:
            match_idx = doi_index[doi_key]
        else:
            for i, existing in enumerate(merged):
                if existing.year and p.year and abs(existing.year - p.year) > 1:
                    continue
                if _title_similarity(norm_titles[i], norm_title) >= title_threshold:
                    match_idx = i
                    break

        if match_idx is None:
            p.sources = [p.source] if p.source else []
            merged.append(p)
            norm_titles.append(norm_title)
            if doi_key:
                doi_index[doi_key] = len(merged) - 1
        else:
            merged[match_idx].merge(p)
            if doi_key and doi_key not in doi_index:
                doi_index[doi_key] = match_idx

    return merged
