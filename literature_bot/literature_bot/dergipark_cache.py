"""Local SQLite (FTS5) cache for DergiPark metadata.

Why a local cache at all: DergiPark's own search page requires a real browser
(it's behind bot verification) and its officially documented API is OAI-PMH
(https://dergipark.org.tr/api/public/oai/), a metadata-*harvesting* protocol,
not a keyword-search one -- it lets you pull every record for a given journal
("set") or date range, but there is no `?q=...` to search across all ~3000
journals directly. So: harvest once (see dergipark_cli.py) into a local FTS5
index, then every `search` command run queries that local index instantly and
offline, with no re-harvesting needed.
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from .models import Paper

DEFAULT_DB_PATH = "dergipark_cache.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    identifier TEXT PRIMARY KEY,
    title TEXT,
    creators TEXT,      -- "; "-joined
    description TEXT,   -- abstract
    publisher TEXT,
    date TEXT,
    year INTEGER,
    doi TEXT,
    url TEXT,
    source TEXT,        -- journal name / volume-issue
    set_spec TEXT,
    language TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    title, description, creators,
    content='records', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts(rowid, title, description, creators)
    VALUES (new.rowid, new.title, new.description, new.creators);
END;

CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, title, description, creators)
    VALUES ('delete', old.rowid, old.title, old.description, old.creators);
END;

CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, title, description, creators)
    VALUES ('delete', old.rowid, old.title, old.description, old.creators);
    INSERT INTO records_fts(rowid, title, description, creators)
    VALUES (new.rowid, new.title, new.description, new.creators);
END;

CREATE TABLE IF NOT EXISTS harvest_log (
    set_spec TEXT PRIMARY KEY,
    last_harvested_at TEXT,
    record_count INTEGER
);
"""


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.executescript(_SCHEMA)
    con.commit()
    return con


def upsert_records(con: sqlite3.Connection, records: List[dict]) -> int:
    """records: list of dicts with keys matching the `records` table columns.
    Returns the number of rows written."""
    if not records:
        return 0
    con.executemany(
        """
        INSERT INTO records (identifier, title, creators, description, publisher,
                              date, year, doi, url, source, set_spec, language)
        VALUES (:identifier, :title, :creators, :description, :publisher,
                :date, :year, :doi, :url, :source, :set_spec, :language)
        ON CONFLICT(identifier) DO UPDATE SET
            title=excluded.title, creators=excluded.creators, description=excluded.description,
            publisher=excluded.publisher, date=excluded.date, year=excluded.year, doi=excluded.doi,
            url=excluded.url, source=excluded.source, set_spec=excluded.set_spec, language=excluded.language
        """,
        records,
    )
    con.commit()
    return len(records)


def mark_harvested(con: sqlite3.Connection, set_spec: str, record_count: int) -> None:
    con.execute(
        """
        INSERT INTO harvest_log (set_spec, last_harvested_at, record_count)
        VALUES (?, datetime('now'), ?)
        ON CONFLICT(set_spec) DO UPDATE SET last_harvested_at=excluded.last_harvested_at,
                                             record_count=excluded.record_count
        """,
        (set_spec, record_count),
    )
    con.commit()


def stats(con: sqlite3.Connection) -> dict:
    total = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    journals = con.execute("SELECT COUNT(*) FROM harvest_log").fetchone()[0]
    return {"total_records": total, "indexed_journals": journals}


def _fts_query(query: str) -> str:
    """Turn a free-text query into a permissive FTS5 MATCH expression: every
    token is required (implicit AND) but there's no phrase/field syntax to
    trip over user input."""
    tokens = [t for t in query.replace('"', " ").split() if t]
    if not tokens:
        return '""'
    return " AND ".join(f'"{t}"' for t in tokens)


def search(db_path: str, query: str, limit: int = 20) -> List[Paper]:
    """Returns [] (never raises) if the DB doesn't exist yet or has no matches."""
    import os

    if not os.path.exists(db_path):
        return []

    con = connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT r.title, r.creators, r.description, r.year, r.doi, r.url, r.source, r.language
            FROM records_fts f
            JOIN records r ON r.rowid = f.rowid
            WHERE records_fts MATCH ?
            ORDER BY bm25(records_fts)
            LIMIT ?
            """,
            (_fts_query(query), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # malformed MATCH expression (e.g. only stopword-like tokens) -> no results, not a crash
        return []
    finally:
        con.close()

    papers = []
    for title, creators, description, year, doi, url, source, language in rows:
        authors = [a.strip() for a in (creators or "").split(";") if a.strip()]
        papers.append(
            Paper(
                title=title or "",
                authors=authors,
                year=year,
                venue=source,
                abstract=description or None,
                doi=doi or None,
                url=url,
                source="DergiPark",
            )
        )
    return papers
