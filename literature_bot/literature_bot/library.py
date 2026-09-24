"""The personal "kütüphane" (library): papers the user explicitly *saved* from
search results, optionally with their full text downloaded. This is separate
from a search run -- a search is disposable, the library is what accumulates
across many searches and is what `draft` builds a write-up from.

Saving is always metadata-only by default; downloading the actual PDF/text is
a separate, explicit opt-in (`save --download`), never automatic.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from typing import List, Optional

from .models import Paper

DEFAULT_DB_PATH = "library.sqlite3"
DEFAULT_FILES_DIR = "kutuphane"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL DEFAULT 'genel',
    saved_at TEXT NOT NULL DEFAULT (datetime('now')),
    paper_json TEXT NOT NULL
);
"""


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)
    con.commit()
    return con


def _paper_to_json(paper: Paper) -> str:
    return json.dumps(asdict(paper), ensure_ascii=False)


def _paper_from_json(text: str) -> Paper:
    data = json.loads(text)
    return Paper(**data)


def save_paper(con: sqlite3.Connection, paper: Paper, collection: str = "genel") -> int:
    cur = con.execute(
        "INSERT INTO saved_papers (collection, paper_json) VALUES (?, ?)",
        (collection, _paper_to_json(paper)),
    )
    con.commit()
    return cur.lastrowid


def update_paper(con: sqlite3.Connection, saved_id: int, paper: Paper) -> None:
    con.execute(
        "UPDATE saved_papers SET paper_json = ? WHERE id = ?",
        (_paper_to_json(paper), saved_id),
    )
    con.commit()


def list_papers(con: sqlite3.Connection, collection: Optional[str] = None) -> List[dict]:
    """Returns [{"id": int, "collection": str, "saved_at": str, "paper": Paper}, ...]"""
    if collection:
        rows = con.execute(
            "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE collection = ? ORDER BY id",
            (collection,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, collection, saved_at, paper_json FROM saved_papers ORDER BY id"
        ).fetchall()
    return [
        {"id": r[0], "collection": r[1], "saved_at": r[2], "paper": _paper_from_json(r[3])}
        for r in rows
    ]


def get_paper(con: sqlite3.Connection, saved_id: int) -> Optional[dict]:
    row = con.execute(
        "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE id = ?",
        (saved_id,),
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "collection": row[1], "saved_at": row[2], "paper": _paper_from_json(row[3])}


def remove_paper(con: sqlite3.Connection, saved_id: int, files_dir: str = DEFAULT_FILES_DIR) -> bool:
    entry = get_paper(con, saved_id)
    if not entry:
        return False
    paper = entry["paper"]
    for path in (paper.fulltext_pdf_path, paper.fulltext_text_path):
        if path and os.path.exists(path) and os.path.abspath(os.path.dirname(path)) == os.path.abspath(files_dir):
            try:
                os.remove(path)
            except OSError:
                pass
    con.execute("DELETE FROM saved_papers WHERE id = ?", (saved_id,))
    con.commit()
    return True


def list_collections(con: sqlite3.Connection) -> List[str]:
    rows = con.execute("SELECT DISTINCT collection FROM saved_papers ORDER BY collection").fetchall()
    return [r[0] for r in rows]
