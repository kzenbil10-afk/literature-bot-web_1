"""Orchestrates querying every requested source in parallel, then dedupes + ranks."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from . import dergipark_cache
from .dedupe import deduplicate
from .models import Paper
from .ranking import _GENERIC_ACADEMIC_TERMS, _tokenize, score_papers
from .sources import REGISTRY

_SUBJECT_ASPECT_RE = re.compile(r"[:;]")
_ASPECT_SPLIT_RE = re.compile(r",|\bve\b|\band\b|\bveya\b|\bor\b", re.IGNORECASE)


def expand_query_variants(query: str, max_variants: int = 4) -> List[str]:
    """Turn a compound "Subject: aspect1, aspect2 ve aspect3" query into
    several tighter sub-queries (subject + each aspect individually), so
    the upstream sources are asked a few focused questions instead of one
    long sentence they may only match loosely on scattered generic words.

    e.g. "İşsizlik: Kavramlar, Ölçüm ve Temel Göstergeler" ->
        ["İşsizlik: Kavramlar, Ölçüm ve Temel Göstergeler" (original, kept as
         one of the variants in case a paper's title matches it verbatim),
         "İşsizlik Kavramlar", "İşsizlik Ölçüm", "İşsizlik Temel Göstergeler"]

    Falls back to [query] unchanged whenever no clear subject/aspect-list
    structure is found, so an ordinary short query (e.g. "Türkiye'de
    işsizlik") is never affected by this.
    """
    parts = _SUBJECT_ASPECT_RE.split(query, maxsplit=1)
    if len(parts) == 2:
        subject, rest = parts[0].strip(), parts[1].strip()
        if not subject:
            return [query]
        aspects = [a.strip() for a in _ASPECT_SPLIT_RE.split(rest) if a.strip()]
    else:
        # No colon/semicolon -- look for a subject/aspect list pattern
        # without one, e.g. "işsizlik kavramları, ölçümü ve göstergeleri".
        # The "subject" is whichever comma/"ve"-separated segment carries a
        # specific (non-generic) term; the rest are treated as aspects of it.
        segments = [s.strip() for s in _ASPECT_SPLIT_RE.split(query) if s.strip()]
        if len(segments) < 3:
            return [query]
        informative_by_segment = [_tokenize(seg) - _GENERIC_ACADEMIC_TERMS for seg in segments]
        subject_idx = next((i for i, terms in enumerate(informative_by_segment) if terms), None)
        if subject_idx is None:
            return [query]
        subject = segments[subject_idx]
        aspects = [s for i, s in enumerate(segments) if i != subject_idx]

    if len(aspects) < 2:
        return [query]

    variants = [f"{subject} {a}" for a in aspects][: max_variants - 1]
    return ([query] + variants)[:max_variants]


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

    # A compound query ("Subject: aspect1, aspect2 ve aspect3") is broken
    # into several tighter sub-queries -- see expand_query_variants -- so
    # the raw candidate pool fetched from each source actually contains
    # papers about each aspect of the subject, rather than whatever loose
    # match the sources' own search happened to return for one long
    # sentence. Every variant is only used for *retrieval*; final
    # relevance scoring below still uses the original query, so this only
    # ever broadens the pool -- it can't loosen what counts as relevant.
    query_variants = expand_query_variants(query)

    def call(variant: str, name: str) -> List[Paper]:
        mod = REGISTRY[name]
        try:
            if name == "openalex":
                return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max, email=openalex_email)
            if name == "semanticscholar":
                return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max, api_key=s2_api_key)
            if name == "pubmed":
                return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max, api_key=pubmed_api_key)
            if name == "arxiv":
                return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max)
            if name == "dergipark":
                return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max, db_path=dergipark_db)
            return mod.search(variant, limit=limit_per_source, year_min=year_min, year_max=year_max)
        except Exception:
            return []

    jobs = [
        (variant, name)
        for variant in query_variants
        for name in source_names
        if name in REGISTRY
    ]
    results: Dict[str, List[Paper]] = {name: [] for name in source_names}
    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as executor:
        futures = {executor.submit(call, variant, name): name for variant, name in jobs}
        for fut in as_completed(futures):
            name = futures[fut]
            results[name].extend(fut.result())

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
