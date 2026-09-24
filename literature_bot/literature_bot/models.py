"""Core data model shared by every source adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Paper:
    """A single bibliographic record, normalized across all sources."""

    title: str
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    citation_count: Optional[int] = None
    source: str = ""
    extra_ids: dict = field(default_factory=dict)  # e.g. {"arxiv": "2301.01234", "pmid": "123456"}

    # populated later by the pipeline
    sources: List[str] = field(default_factory=list)
    score: float = 0.0

    # populated by translation.py — never used for citation, reading aid only
    title_tr: Optional[str] = None
    abstract_tr: Optional[str] = None

    # populated by fulltext.py when --fetch-fulltext is used
    fulltext_status: Optional[str] = None  # "ok" | "pdf_only" | "unavailable" | None (not attempted)
    fulltext_pdf_path: Optional[str] = None
    fulltext_text_path: Optional[str] = None
    fulltext_source_url: Optional[str] = None
    fulltext_source_method: Optional[str] = None  # "direct" | "unpaywall" | "citation_meta"
    fulltext_method: Optional[str] = None  # "text-layer" | "ocr" | "none"
    fulltext_chars: Optional[int] = None
    fulltext_possibly_garbled: bool = False
    fulltext_error: Optional[str] = None

    # populated by the WEB APP's save flow (literature_bot/webapp.py) instead of
    # fulltext_text_path: the actual extracted text, stored inline in the paper's
    # own JSON (and so persisted wherever that JSON is persisted -- e.g. Turso),
    # rather than as a path to a file on a web host's filesystem, which may not
    # survive a restart. The CLI (fulltext.py/library.py) keeps using
    # fulltext_text_path as a real file path; this field is simply unused there.
    fulltext_text_inline: Optional[str] = None

    # populated by fulltext.preview_fulltexts() when --preview-fulltext is used in
    # `search` -- an ephemeral, short excerpt only (the downloaded PDF is discarded
    # right after). Distinct from the fulltext_* fields above, which are the result
    # of an explicit, persistent `save --download`.
    preview_available: Optional[bool] = None
    preview_text: Optional[str] = None
    preview_source_method: Optional[str] = None  # "direct" | "unpaywall" | "citation_meta"
    preview_method: Optional[str] = None  # "text-layer" | "ocr" | "none"
    preview_reason: Optional[str] = None  # why unavailable, when it is

    @classmethod
    def from_dict(cls, data: dict) -> "Paper":
        """Reconstructs a Paper from a plain dict (e.g. JSON the web frontend
        sends back after round-tripping a search result). Unknown/extra keys
        are dropped rather than raising, so an older client or a dict with a
        stray field never breaks the request."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def merge(self, other: "Paper") -> "Paper":
        """Merge a duplicate record into this one, preferring the more complete field."""
        self.abstract = self.abstract or other.abstract
        self.doi = self.doi or other.doi
        self.venue = self.venue or other.venue
        self.pdf_url = self.pdf_url or other.pdf_url
        self.url = self.url or other.url
        if other.year and not self.year:
            self.year = other.year
        if other.citation_count is not None:
            self.citation_count = max(self.citation_count or 0, other.citation_count)
        if len(other.authors) > len(self.authors):
            self.authors = other.authors
        self.extra_ids.update(other.extra_ids)
        for s in (other.sources or [other.source]):
            if s and s not in self.sources:
                self.sources.append(s)
        self.title_tr = self.title_tr or other.title_tr
        self.abstract_tr = self.abstract_tr or other.abstract_tr
        return self

    def first_author_surname(self) -> str:
        if not self.authors:
            return "N.N."
        return self.authors[0].split()[-1] if self.authors[0].split() else "N.N."

    def cite_key(self) -> str:
        surname = "".join(ch for ch in self.first_author_surname().lower() if ch.isalpha()) or "anon"
        yr = str(self.year) if self.year else "nd"
        first_word = ""
        for w in (self.title or "").split():
            w2 = "".join(ch for ch in w.lower() if ch.isalpha())
            if w2 and w2 not in {"the", "a", "an", "on", "of", "for", "and"}:
                first_word = w2
                break
        return f"{surname}{yr}{first_word}"
