"""Orchestrates querying every requested source in parallel, then dedupes + ranks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from . import dergipark_cache
from .dedupe import deduplicate
from .models import Paper
from .ranking import score_papers
from .sources import REGISTRY


def run_search(
    query: str,
    source_names: List[str],
    limit_per_source: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    openalex_email: Optional[str] = None,
    s2_api_key: Optional[str] = None,
    pubmed_api_key: Optional[str] = None,
    dergipark_db: str = dergipark_cache.DEFAULT_DB_PATH,
) -> Tuple[List[Paper], Dict[str, int], int]:
    """Returns (ranked_unique_papers, per_source_counts, raw_total_before_dedupe)."""

    def call(name: str) -> List[Paper]:
        mod = REGISTRY[name]
        try:
            if name == "openalex":
                return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max, email=openalex_email)
            if name == "semanticscholar":
                return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max, api_key=s2_api_key)
            if name == "pubmed":
                return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max, api_key=pubmed_api_key)
            if name == "arxiv":
                return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max)
            if name == "dergipark":
                return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max, db_path=dergipark_db)
            return mod.search(query, limit=limit_per_source, year_min=year_min, year_max=year_max)
        except Exception:
            return []

    results: Dict[str, List[Paper]] = {}
    with ThreadPoolExecutor(max_workers=max(len(source_names), 1)) as executor:
        futures = {executor.submit(call, name): name for name in source_names if name in REGISTRY}
        for fut in as_completed(futures):
            name = futures[fut]
            results[name] = fut.result()

    all_papers: List[Paper] = []
    counts: Dict[str, int] = {}
    for name in source_names:
        papers = results.get(name, [])
        counts[name] = len(papers)
        all_papers.extend(papers)

    raw_total = len(all_papers)
    unique = deduplicate(all_papers)
    ranked = score_papers(unique, query)

    # Drop results that have essentially no real relevance to the query --
    # these used to survive purely on citation count/recency (see
    # ranking.py) and show up as e.g. logistics papers for an unemployment
    # search. Keep a small fallback so a genuinely narrow/niche query still
    # returns *something* rather than an empty page, instead of silently
    # padding it out with off-topic results.
    _MIN_RELEVANCE = 0.10
    _MIN_FALLBACK = 3
    relevant = [p for p in ranked if p.score >= _MIN_RELEVANCE]
    if len(relevant) >= _MIN_FALLBACK or not ranked:
        ranked = relevant
    else:
        ranked = ranked[: max(len(relevant), _MIN_FALLBACK)]

    return ranked, counts, raw_total
