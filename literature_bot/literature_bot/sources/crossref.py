"""Crossref adapter — DOI registry covering most journals/conferences, free, no key.

https://api.crossref.org/swagger-ui/index.html
"""
from __future__ import annotations

import html
import re
import urllib.parse
from typing import List, Optional

from ..models import Paper
from .base import get_json

BASE_URL = "https://api.crossref.org/works"

_DOI_URL_PREFIX_RE = re.compile(r"^\s*(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)


def _strip_jats(text: Optional[str]) -> Optional[str]:
    """Crossref abstracts are JATS-tagged XML fragments (<jats:p>...</jats:p>), and some
    publishers submit them with entities already HTML-escaped once (or twice), e.g.
    "&amp;lt;p&amp;gt;...". Unescape before *and* after stripping tags so both cases end
    up as clean plain text instead of literal "&lt;p&gt;" junk in the report."""
    if not text:
        return None
    unescaped = html.unescape(html.unescape(text))
    stripped = re.sub(r"<[^>]+>", " ", unescaped)
    cleaned = re.sub(r"\s+", " ", stripped).strip()
    return cleaned or None


def _item_to_paper(item: dict) -> Optional[Paper]:
    titles = item.get("title") or []
    if not titles:
        return None
    authors = []
    for a in item.get("author", []) or []:
        name = " ".join(p for p in [a.get("given"), a.get("family")] if p)
        if name:
            authors.append(name)
    year = None
    issued = (item.get("issued") or {}).get("date-parts") or []
    if issued and issued[0]:
        year = issued[0][0]
    venue_list = item.get("container-title") or []

    return Paper(
        title=titles[0],
        authors=authors,
        year=year,
        venue=venue_list[0] if venue_list else None,
        abstract=_strip_jats(item.get("abstract")),
        doi=item.get("DOI"),
        url=item.get("URL"),
        citation_count=item.get("is-referenced-by-count"),
        source="Crossref",
    )


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    email: Optional[str] = None,
) -> List[Paper]:
    params = {
        "query": query,
        "rows": min(limit, 50),
        "select": "DOI,title,author,issued,container-title,abstract,is-referenced-by-count,URL,type",
        "sort": "relevance",
    }
    filters = []
    if year_min:
        filters.append(f"from-pub-date:{year_min}-01-01")
    if year_max:
        filters.append(f"until-pub-date:{year_max}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    if email:
        params["mailto"] = email

    data = get_json(BASE_URL, params=params)
    if not data or "message" not in data:
        return []

    papers: List[Paper] = []
    for item in data["message"].get("items", []):
        p = _item_to_paper(item)
        if p:
            papers.append(p)
    return papers


def normalize_doi(raw: str) -> str:
    """Accepts a bare DOI ("10.1234/abc"), a doi.org URL, or either with
    stray whitespace, and returns the bare DOI. Users pasting from a
    journal page or Google Scholar's "Cite" popup commonly copy the full
    URL form, so this is applied before every lookup."""
    text = (raw or "").strip()
    text = _DOI_URL_PREFIX_RE.sub("", text)
    return text.strip().strip("/")


def lookup_by_doi(doi: str, email: Optional[str] = None) -> Optional[Paper]:
    """Fetch a single work's metadata directly by DOI, for the "fill this
    in from a DOI" convenience on the web app's manual-add-source form --
    as opposed to search(), which runs a free-text relevance query."""
    clean = normalize_doi(doi)
    if not clean:
        return None
    params = {"mailto": email} if email else None
    data = get_json(f"{BASE_URL}/{urllib.parse.quote(clean, safe='')}", params=params)
    if not data or "message" not in data:
        return None
    return _item_to_paper(data["message"])
