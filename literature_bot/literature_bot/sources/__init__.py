from . import arxiv, crossref, dergipark, openalex, pubmed, semantic_scholar, yok_tez

REGISTRY = {
    "openalex": openalex,
    "crossref": crossref,
    "arxiv": arxiv,
    "semanticscholar": semantic_scholar,
    "pubmed": pubmed,
    "dergipark": dergipark,
    "yok_tez": yok_tez,
}

ALL_SOURCES = list(REGISTRY.keys())