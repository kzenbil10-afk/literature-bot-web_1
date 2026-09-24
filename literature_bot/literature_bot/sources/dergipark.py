"""DergiPark adapter — TÜBİTAK ULAKBİM's aggregator for ~3000+ Turkish
academic journals (https://dergipark.org.tr). No live keyword-search API
exists (the web UI is behind bot verification; the documented API is
OAI-PMH, a metadata-*harvesting* protocol, not a search one). So this module:

  - harvests journal metadata via OAI-PMH into a local SQLite/FTS5 cache
    (see dergipark_cache.py and dergipark_cli.py for the indexing commands),
  - and `search()` here just queries that local cache.

If the cache hasn't been built yet, `search()` returns [] rather than
failing — the CLI surfaces a clear one-line hint telling the user how to
build it (see cli.py).
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator, List, Optional

from .. import dergipark_cache
from ..models import Paper
from .base import USER_AGENT, get_text

OAI_BASE = "https://dergipark.org.tr/api/public/oai/"
NS = "{http://www.openarchives.org/OAI/2.0/}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
OAI_DC_NS = "{http://www.openarchives.org/OAI/2.0/oai_dc/}"

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def _text_list(el, tag: str) -> List[str]:
    return [
        html.unescape((child.text or "").strip())
        for child in el.findall(f"{DC_NS}{tag}")
        if child.text
    ]


def fetch_sets(timeout: int = 30) -> List[dict]:
    """All journals ('sets') DergiPark exposes via OAI-PMH, as
    [{"set_spec": ..., "set_name": ...}, ...]. A few thousand entries;
    cheap enough to fetch fresh each time it's needed."""
    sets: List[dict] = []
    token = None
    while True:
        params = {"verb": "ListSets"} if not token else {"verb": "ListSets", "resumptionToken": token}
        text = get_text(OAI_BASE, params=params, timeout=timeout)
        if not text:
            break
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            break
        list_sets = root.find(f"{NS}ListSets")
        if list_sets is None:
            break
        for set_el in list_sets.findall(f"{NS}set"):
            spec = set_el.findtext(f"{NS}setSpec")
            name = set_el.findtext(f"{NS}setName")
            if spec:
                sets.append({"set_spec": spec, "set_name": (name or spec).strip()})
        token_el = list_sets.find(f"{NS}resumptionToken")
        token = token_el.text if token_el is not None and token_el.text else None
        if not token:
            break
        time.sleep(0.3)
    return sets


def _parse_record(record_el) -> Optional[dict]:
    header = record_el.find(f"{NS}header")
    if header is not None and header.get("status") == "deleted":
        return None
    identifier_el = header.find(f"{NS}identifier") if header is not None else None
    identifier = identifier_el.text if identifier_el is not None else None

    metadata = record_el.find(f"{NS}metadata")
    if metadata is None:
        return None
    dc = metadata.find(f"{OAI_DC_NS}dc")
    if dc is None:
        return None

    title = " ".join(_text_list(dc, "title")) or None
    if not title:
        return None
    creators = _text_list(dc, "creator")
    descriptions = _text_list(dc, "description")
    publishers = _text_list(dc, "publisher")
    dates = _text_list(dc, "date")
    sources = _text_list(dc, "source")
    languages = _text_list(dc, "language")
    identifiers = _text_list(dc, "identifier")

    landing_url = next((i for i in identifiers if "dergipark.org.tr" in i), None) or (identifiers[0] if identifiers else None)
    doi = None
    for i in identifiers:
        m = _DOI_RE.search(i)
        if m:
            doi = m.group(0)
            break

    year = None
    if dates:
        digits = "".join(ch for ch in dates[0][:4] if ch.isdigit())
        if len(digits) == 4:
            year = int(digits)

    set_spec_el = header.find(f"{NS}setSpec") if header is not None else None

    return {
        "identifier": identifier or landing_url or title,
        "title": title,
        "creators": "; ".join(creators),
        "description": " ".join(descriptions) or None,
        "publisher": publishers[0] if publishers else None,
        "date": dates[0] if dates else None,
        "year": year,
        "doi": doi,
        "url": landing_url,
        "source": sources[0] if sources else None,
        "set_spec": set_spec_el.text if set_spec_el is not None else None,
        "language": languages[0] if languages else None,
    }


def harvest_records(
    set_spec: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    max_records: Optional[int] = None,
    timeout: int = 30,
    polite_delay: float = 0.4,
) -> Iterator[List[dict]]:
    """Yields batches (pages) of parsed record dicts, ready for
    dergipark_cache.upsert_records(). `set_spec=None` harvests across every
    journal DergiPark hosts -- large; prefer passing specific journals for a
    focused index (see dergipark_cli.py `list-sets` to find setSpecs)."""
    fetched = 0
    token = None
    while True:
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        else:
            params = {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
            if set_spec:
                params["set"] = set_spec
            if since:
                params["from"] = since
            if until:
                params["until"] = until

        text = get_text(OAI_BASE, params=params, timeout=timeout)
        if not text:
            return
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return

        error = root.find(f"{NS}error")
        if error is not None:
            return  # e.g. noRecordsMatch -- nothing more to do

        list_records = root.find(f"{NS}ListRecords")
        if list_records is None:
            return

        batch = []
        for record_el in list_records.findall(f"{NS}record"):
            parsed = _parse_record(record_el)
            if parsed:
                batch.append(parsed)
        if batch:
            yield batch
            fetched += len(batch)

        if max_records and fetched >= max_records:
            return

        token_el = list_records.find(f"{NS}resumptionToken")
        token = token_el.text if token_el is not None and token_el.text else None
        if not token:
            return
        time.sleep(polite_delay)


def search(
    query: str,
    limit: int = 20,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    db_path: str = dergipark_cache.DEFAULT_DB_PATH,
) -> List[Paper]:
    papers = dergipark_cache.search(db_path, query, limit=limit)
    if year_min or year_max:
        papers = [
            p for p in papers
            if p.year and (not year_min or p.year >= year_min) and (not year_max or p.year <= year_max)
        ]
    return papers
