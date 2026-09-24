"""Library storage backend for the WEB APP (webapp.py) -- distinct from
library.py, which is the CLI's local-sqlite-only backend and is left
untouched so the CLI keeps working exactly as before.

Why this exists: the CLI's library.py always writes to a local .sqlite3
file, which is fine on your own machine but would silently lose everything
on a free web host whose filesystem is wiped on every restart/redeploy
(Render's free tier does this). So this module picks its backend at
connect() time:

  - TURSO_DATABASE_URL set  -> Turso (libsql), a free, persistent, real
    database reachable over the network. This is what the deployed web app
    uses in production.
  - not set                -> a local .sqlite3 file, same schema, just like
    library.py. This is what running webapp.py on your own machine for
    testing uses -- no Turso account needed just to try it out locally.

Both backends expose the exact same small API, so webapp.py never needs to
know or care which one is active.

Multi-user note (added 2026-09-24): each saved paper now carries an `owner`
(the username that saved it), and every read/write is scoped to a single
owner so several people can share one deployment/database while each only
ever sees their own library. A small `users` table holds username +
password hash for the simple built-in login (see webapp.py's /api/auth/*).
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Optional

from .models import Paper

DEFAULT_DB_PATH = "web_library.sqlite3"

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS saved_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection TEXT NOT NULL DEFAULT 'genel',
    saved_at TEXT NOT NULL,
    paper_json TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT ''
);
"""

# libSQL (Turso) speaks the same SQL dialect as SQLite, but we spell the
# schema out explicitly (no `datetime('now')` default) since we set saved_at
# from Python ourselves for both backends -- one less thing that could behave
# subtly differently between the two.
_SCHEMA_TURSO = _SCHEMA_SQLITE

_SCHEMA_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Deployments created before the multi-user feature already have a
# saved_papers table without the `owner` column. CREATE TABLE IF NOT EXISTS
# won't add it to an existing table, so we try an explicit ALTER TABLE once
# at backend startup and just ignore the error it raises on every later
# startup once the column already exists (there's no portable
# "ADD COLUMN IF NOT EXISTS" in SQLite/libSQL).
_ADD_OWNER_COLUMN_SQL = "ALTER TABLE saved_papers ADD COLUMN owner TEXT NOT NULL DEFAULT ''"


def _paper_to_json(paper: Paper) -> str:
    return json.dumps(asdict(paper), ensure_ascii=False)


def _paper_from_json(text: str) -> Paper:
    # Tolerate old rows / dicts missing fields added later (e.g. a field
    # introduced after some rows were already saved) -- never hard-fail a
    # library listing just because the schema grew a field.
    return Paper.from_dict(json.loads(text))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _SqliteBackend:
    """Local-file fallback, used when TURSO_DATABASE_URL isn't set (i.e.
    running webapp.py locally for testing, without a Turso account)."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.executescript(_SCHEMA_SQLITE)
        self.con.executescript(_SCHEMA_USERS)
        cols = [r[1] for r in self.con.execute("PRAGMA table_info(saved_papers)").fetchall()]
        if "owner" not in cols:
            self.con.execute(_ADD_OWNER_COLUMN_SQL)
        self.con.commit()

    def save_paper(self, paper: Paper, collection: str, owner: str = "") -> int:
        cur = self.con.execute(
            "INSERT INTO saved_papers (collection, saved_at, paper_json, owner) VALUES (?, ?, ?, ?)",
            (collection, _now_iso(), _paper_to_json(paper), owner),
        )
        self.con.commit()
        return cur.lastrowid

    def list_papers(self, collection: Optional[str] = None, owner: Optional[str] = None) -> List[dict]:
        conds, params = [], []
        if collection:
            conds.append("collection = ?")
            params.append(collection)
        if owner is not None:
            conds.append("owner = ?")
            params.append(owner)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows = self.con.execute(
            f"SELECT id, collection, saved_at, paper_json FROM saved_papers {where} ORDER BY id DESC",
            params,
        ).fetchall()
        return [
            {"id": r[0], "collection": r[1], "saved_at": r[2], "paper": _paper_from_json(r[3])}
            for r in rows
        ]

    def get_paper(self, saved_id: int, owner: Optional[str] = None) -> Optional[dict]:
        if owner is not None:
            row = self.con.execute(
                "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE id = ? AND owner = ?",
                (saved_id, owner),
            ).fetchone()
        else:
            row = self.con.execute(
                "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE id = ?",
                (saved_id,),
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "collection": row[1], "saved_at": row[2], "paper": _paper_from_json(row[3])}

    def remove_paper(self, saved_id: int, owner: Optional[str] = None) -> bool:
        if owner is not None:
            cur = self.con.execute(
                "DELETE FROM saved_papers WHERE id = ? AND owner = ?", (saved_id, owner)
            )
        else:
            cur = self.con.execute("DELETE FROM saved_papers WHERE id = ?", (saved_id,))
        self.con.commit()
        return cur.rowcount > 0

    def list_collections(self, owner: Optional[str] = None) -> List[str]:
        if owner is not None:
            rows = self.con.execute(
                "SELECT DISTINCT collection FROM saved_papers WHERE owner = ? ORDER BY collection", (owner,)
            ).fetchall()
        else:
            rows = self.con.execute("SELECT DISTINCT collection FROM saved_papers ORDER BY collection").fetchall()
        return [r[0] for r in rows]

    def create_user(self, username: str, password_hash: str) -> int:
        cur = self.con.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, _now_iso()),
        )
        self.con.commit()
        return cur.lastrowid

    def get_user(self, username: str) -> Optional[dict]:
        row = self.con.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2], "created_at": row[3]}

    def delete_user(self, username: str) -> bool:
        cur = self.con.execute("DELETE FROM users WHERE username = ?", (username,))
        self.con.commit()
        return cur.rowcount > 0


class _TursoBackend:
    """Production backend: Turso (libsql-client), a free, persistent,
    network-reachable SQLite-compatible database -- survives Render's free
    Web Service being restarted/redeployed/spun down, unlike the local
    filesystem."""

    def __init__(self, url: str, auth_token: Optional[str]):
        import libsql_client

        # libsql_client turns a "libsql://" URL into a "wss://" (WebSocket)
        # connection under the hood. That works fine from most places, but
        # some hosts' outbound network/proxy setup rejects the WebSocket
        # upgrade handshake outright ("Invalid response status") even though
        # plain HTTPS to the same host is fine -- observed on Render's free
        # tier as of 2026-09-24. Turso serves the same database over both
        # protocols, so normalizing "libsql://" (and bare "wss://") to
        # "https://" here sidesteps that class of failure entirely, without
        # requiring TURSO_DATABASE_URL itself to be re-entered correctly.
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        elif url.startswith("wss://"):
            url = "https://" + url[len("wss://"):]

        self._client = libsql_client.create_client_sync(url=url, auth_token=auth_token)
        self._client.execute(_SCHEMA_TURSO)
        self._client.execute(_SCHEMA_USERS)
        try:
            self._client.execute(_ADD_OWNER_COLUMN_SQL)
        except Exception:
            pass  # column already exists from a previous deploy -- fine.

    def save_paper(self, paper: Paper, collection: str, owner: str = "") -> int:
        rs = self._client.execute(
            "INSERT INTO saved_papers (collection, saved_at, paper_json, owner) VALUES (?, ?, ?, ?) RETURNING id",
            [collection, _now_iso(), _paper_to_json(paper), owner],
        )
        return int(rs.rows[0][0])

    def list_papers(self, collection: Optional[str] = None, owner: Optional[str] = None) -> List[dict]:
        conds, params = [], []
        if collection:
            conds.append("collection = ?")
            params.append(collection)
        if owner is not None:
            conds.append("owner = ?")
            params.append(owner)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rs = self._client.execute(
            f"SELECT id, collection, saved_at, paper_json FROM saved_papers {where} ORDER BY id DESC",
            params,
        )
        return [
            {"id": r[0], "collection": r[1], "saved_at": r[2], "paper": _paper_from_json(r[3])}
            for r in rs.rows
        ]

    def get_paper(self, saved_id: int, owner: Optional[str] = None) -> Optional[dict]:
        if owner is not None:
            rs = self._client.execute(
                "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE id = ? AND owner = ?",
                [saved_id, owner],
            )
        else:
            rs = self._client.execute(
                "SELECT id, collection, saved_at, paper_json FROM saved_papers WHERE id = ?",
                [saved_id],
            )
        if not rs.rows:
            return None
        r = rs.rows[0]
        return {"id": r[0], "collection": r[1], "saved_at": r[2], "paper": _paper_from_json(r[3])}

    def remove_paper(self, saved_id: int, owner: Optional[str] = None) -> bool:
        if owner is not None:
            rs = self._client.execute(
                "DELETE FROM saved_papers WHERE id = ? AND owner = ?", [saved_id, owner]
            )
        else:
            rs = self._client.execute("DELETE FROM saved_papers WHERE id = ?", [saved_id])
        return rs.rows_affected > 0

    def list_collections(self, owner: Optional[str] = None) -> List[str]:
        if owner is not None:
            rs = self._client.execute(
                "SELECT DISTINCT collection FROM saved_papers WHERE owner = ? ORDER BY collection", [owner]
            )
        else:
            rs = self._client.execute("SELECT DISTINCT collection FROM saved_papers ORDER BY collection")
        return [r[0] for r in rs.rows]

    def create_user(self, username: str, password_hash: str) -> int:
        rs = self._client.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?) RETURNING id",
            [username, password_hash, _now_iso()],
        )
        return int(rs.rows[0][0])

    def get_user(self, username: str) -> Optional[dict]:
        rs = self._client.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?", [username]
        )
        if not rs.rows:
            return None
        r = rs.rows[0]
        return {"id": r[0], "username": r[1], "password_hash": r[2], "created_at": r[3]}

    def delete_user(self, username: str) -> bool:
        rs = self._client.execute("DELETE FROM users WHERE username = ?", [username])
        return rs.rows_affected > 0


_backend = None  # module-level singleton, built lazily on first use


def get_backend():
    """Returns the active storage backend, building it (and its connection)
    on first call. Turso if TURSO_DATABASE_URL is set, else local sqlite."""
    global _backend
    if _backend is not None:
        return _backend

    turso_url = os.environ.get("TURSO_DATABASE_URL")
    if turso_url:
        _backend = _TursoBackend(turso_url, os.environ.get("TURSO_AUTH_TOKEN"))
    else:
        _backend = _SqliteBackend(os.environ.get("WEB_LIBRARY_DB", DEFAULT_DB_PATH))
    return _backend


def backend_name() -> str:
    return "turso" if os.environ.get("TURSO_DATABASE_URL") else "sqlite (yerel dosya)"
