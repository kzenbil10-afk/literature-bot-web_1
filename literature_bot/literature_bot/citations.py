"""APA-style citation strings and BibTeX export — so results drop straight into
a thesis reference manager (Zotero/Mendeley/Overleaf)."""
from __future__ import annotations

from typing import List

from .models import Paper


def _format_authors_apa(authors: List[str]) -> str:
    def one(name: str) -> str:
        parts = name.strip().split()
        if len(parts) < 2:
            return name
        surname = parts[-1]
        initials = " ".join(f"{p[0]}." for p in parts[:-1] if p)
        return f"{surname}, {initials}"

    if not authors:
        return "N.N."
    formatted = [one(a) for a in authors]
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    return ", ".join(formatted[:19]) + ", ... " + formatted[-1]


def format_apa(paper: Paper) -> str:
    authors = _format_authors_apa(paper.authors)
    year = paper.year or "t.y."
    title = paper.title.rstrip(".")
    venue = f" *{paper.venue}*." if paper.venue else ""
    link = f" https://doi.org/{paper.doi}" if paper.doi else (f" {paper.url}" if paper.url else "")
    return f"{authors} ({year}). {title}.{venue}{link}".strip()


def to_bibtex(paper: Paper, key: str = None) -> str:
    key = key or paper.cite_key()
    entry_type = "article"
    fields = {
        "title": "{" + paper.title.replace("{", "").replace("}", "") + "}",
        "author": " and ".join(paper.authors) if paper.authors else None,
        "year": str(paper.year) if paper.year else None,
        "journal": paper.venue if paper.venue else None,
        "doi": paper.doi,
        "url": paper.url or paper.pdf_url,
        "note": f"Retrieved via {'/'.join(paper.sources) or paper.source}",
    }
    lines = [f"@{entry_type}{{{key},"]
    for k, v in fields.items():
        if v:
            v_clean = str(v).replace("\n", " ").strip()
            lines.append(f"  {k} = {{{v_clean}}},")
    lines.append("}")
    return "\n".join(lines)


def bibliography_bibtex(papers: List[Paper]) -> str:
    used_keys = {}
    entries = []
    for p in papers:
        base_key = p.cite_key()
        key = base_key
        n = 1
        while key in used_keys:
            n += 1
            key = f"{base_key}{chr(96 + n)}"  # a, b, c...
        used_keys[key] = True
        entries.append(to_bibtex(p, key=key))
    return "\n\n".join(entries) + "\n"
