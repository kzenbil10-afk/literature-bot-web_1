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

# Python's default str.lower() is locale-unaware: the Turkish capital dotted
# 'İ' (U+0130) lowercases to 'i' + a COMBINING DOT ABOVE (U+0307) -- two
# code points, not plain 'i'. Since that combining mark isn't in the word
# regex below, a leading "İ" silently split the word in two and dropped the
# "i" (e.g. "İşsizlik" -> token "şsizlik", missing its first letter),
# producing a *different* token than the same word written in ordinary
# lowercase mid-sentence ("işsizlik" -> "işsizlik", correct). Since titles
# are Capitalized-Per-Word while abstracts use normal sentence case, this
# silently broke query/abstract matching for any word starting with İ --
# applying correct Turkish casing rules before the generic lowercase avoids
# the combining-mark artifact entirely.
_TR_UPPER_MAP = str.maketrans({"İ": "i", "I": "ı"})


def _tokenize(text: str) -> set:
    text = _APOSTROPHE_SUFFIX_RE.sub("", text or "")
    text = text.translate(_TR_UPPER_MAP).lower()
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", text)
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


# Generic academic/methodological vocabulary: words that show up in the
# title or abstract of almost any scholarly paper regardless of its actual
# subject (Turkish and English). A query like "İşsizlik: Kavramlar, Ölçüm ve
# Temel Göstergeler" ("Unemployment: Concepts, Measurement and Key
# Indicators") has exactly one topic-specific word ("işsizlik") and four of
# these filler words -- without downweighting them, a completely unrelated
# paper that merely happens to share "kavramlar"/"temel" (e.g. one about art
# theory) could match nearly as well as a genuine unemployment paper. These
# terms still count a little (for fine-grained sorting) but never carry
# enough weight on their own to make an off-topic paper look relevant, and
# _score_one below additionally requires that at least one *specific*
# (non-generic) query term match somewhere -- matching filler words alone is
# never enough to keep a result.
_GENERIC_ACADEMIC_TERMS = {
    "kavram", "kavramlar", "kavramsal", "temel", "temelleri", "temeli",
    "ölçüm", "ölçümü", "ölçümler", "gösterge", "göstergeler", "göstergesi",
    "analiz", "analizi", "yöntem", "yöntemi", "yöntemler", "yaklaşım",
    "yaklaşımı", "inceleme", "incelemesi", "araştırma", "araştırması",
    "çalışma", "çalışması", "uygulama", "uygulaması", "değerlendirme",
    "değerlendirmesi", "ilişki", "ilişkisi", "etki", "etkisi", "model",
    "modeli", "teori", "teorisi", "sistem", "sistemi", "süreç", "süreci",
    "veri", "veriler", "sonuç", "sonuçlar", "giriş", "özet", "genel",
    "örnek", "örneği", "perspektif", "perspektifi", "bakış", "çerçeve",
    "çerçevesi", "strateji", "stratejisi", "politika", "politikası",
    "faktör", "faktörler", "unsur", "unsurları", "boyut", "boyutları",
    "rol", "rolü", "önem", "önemi", "gelişim", "gelişimi", "gelişme",
    "gelişmesi",
    "concept", "concepts", "conceptual", "basic", "basics", "fundamental",
    "fundamentals", "measurement", "measurements", "indicator",
    "indicators", "analysis", "method", "methods", "methodology",
    "approach", "approaches", "review", "study", "studies", "application",
    "applications", "evaluation", "assessment", "relationship", "effect",
    "effects", "model", "models", "theory", "theories", "system",
    "systems", "process", "processes", "data", "result", "results",
    "introduction", "summary", "overview", "perspective", "framework",
    "strategy", "strategies", "policy", "policies", "factor", "factors",
    "role", "importance", "development",
}


def score_papers(papers: List[Paper], query: str, weights=None) -> List[Paper]:
    """Assign a 0-1 relevance score to each paper and sort descending.

    weights: dict with keys term, citation, recency (default 0.5 / 0.3 / 0.2).
    """
    weights = weights or {"term": 0.5, "citation": 0.3, "recency": 0.2}
    query_terms = _tokenize(query)
    if not papers:
        return papers

    # The specific, topic-carrying words in the query -- everything except
    # generic academic filler (see _GENERIC_ACADEMIC_TERMS above). A result
    # must match at least one of these to be considered relevant at all; if
    # the whole query happens to be made of filler words, fall back to
    # treating every term as "specific" so we don't gate on nothing.
    specific_terms = query_terms - _GENERIC_ACADEMIC_TERMS or query_terms

    def _term_weight(t: str) -> float:
        return 0.25 if t in _GENERIC_ACADEMIC_TERMS else 1.0

    max_citations = max((p.citation_count or 0) for p in papers) or 1
    years = [p.year for p in papers if p.year]
    min_year, max_year = (min(years), max(years)) if years else (None, None)

    for p in papers:
        title_terms = _tokenize(p.title)
        abstract_terms = _tokenize(p.abstract or "")
        if query_terms:
            if specific_terms and not (specific_terms & (title_terms | abstract_terms)):
                # No topic-specific query term appears anywhere in this
                # paper -- matching only filler words (e.g. "kavramlar",
                # "temel") is not enough to call it relevant.
                term_score = 0.0
            else:
                weight_sum = sum(_term_weight(t) for t in query_terms)
                weighted_title_hits = sum(_term_weight(t) for t in query_terms if t in title_terms)
                weighted_abstract_hits = sum(_term_weight(t) for t in query_terms if t in abstract_terms)
                term_hits = weighted_title_hits * 2 + weighted_abstract_hits
                term_score = min(term_hits / (weight_sum * 2), 1.0) if weight_sum else 0.5
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
