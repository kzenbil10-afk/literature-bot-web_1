"""PubMed adapter (NCBI E-utilities) — biomedical / life-sciences literature. Free, no key
required, but an api_key raises the rate limit from 3 to 10 req/s.

https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..models import Paper
from .base import get_json, get_text

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _text(el, path):
    found = el.find(path)
    return found.text if found is not None and found.text else None


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    api_key: Optional[str] = None,
) -> List[Paper]:
    term = query
    if year_min or year_max:
        lo = year_min or 1900
        hi = year_max or 2100
        term = f"({query}) AND ({lo}:{hi}[dp])"

    params = {"db": "pubmed", "term": term, "retmax": min(limit, 50), "retmode": "json"}
    if api_key:
        params["api_key"] = api_key
    search_data = get_json(ESEARCH_URL, params=params)
    if not search_data:
        return []
    ids = (search_data.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []

    fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml", "rettype": "abstract"}
    if api_key:
        fetch_params["api_key"] = api_key
    xml_text = get_text(EFETCH_URL, params=fetch_params)
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    papers: List[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        title = _text(article, ".//ArticleTitle") or ""
        if not title:
            continue
        abstract_parts = [
            (node.text or "") for node in article.findall(".//Abstract/AbstractText")
        ]
        abstract = " ".join(p.strip() for p in abstract_parts if p.strip()) or None

        authors = []
        for a in article.findall(".//AuthorList/Author"):
            last = _text(a, "LastName")
            fore = _text(a, "ForeName") or _text(a, "Initials")
            if last:
                authors.append(f"{fore} {last}".strip() if fore else last)

        year = None
        year_text = _text(article, ".//PubDate/Year") or _text(article, ".//PubDate/MedlineDate")
        if year_text:
            digits = "".join(ch for ch in year_text[:4] if ch.isdigit())
            year = int(digits) if len(digits) == 4 else None

        venue = _text(article, ".//Journal/Title")
        pmid = _text(article, ".//PMID")
        doi = None
        # IMPORTANT: scope strictly to PubmedData/ArticleIdList (the article's own IDs).
        # A plain ".//ArticleIdList/ArticleId" search also matches DOIs buried inside
        # PubmedData/ReferenceList/Reference/ArticleIdList (the article's *cited*
        # references), and the last match wins — silently attaching a random cited
        # paper's DOI to this record instead of its own.
        own_id_list = article.find("PubmedData/ArticleIdList")
        if own_id_list is not None:
            for eid in own_id_list.findall("ArticleId"):
                if eid.get("IdType") == "doi":
                    doi = eid.text
                    break

        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                doi=doi,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                citation_count=None,
                source="PubMed",
                extra_ids={"pmid": pmid} if pmid else {},
            )
        )
    return papers
