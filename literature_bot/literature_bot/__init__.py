from . import arxiv, crossref, dergipark, openalex, pubmed, semantic_scholar

REGISTRY = {
    "openalex": openalex,
    "crossref": crossref,
    "arxiv": arxiv,
    "semanticscholar": semantic_scholar,
    "pubmed": pubmed,
    "dergipark": dergipark,
}

ALL_SOURCES = list(REGISTRY.keys())
