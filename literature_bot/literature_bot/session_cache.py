"""The "last search results" cache: `search` writes its ranked result list here
so a later, separate `save <numara>` invocation can refer to "result #3" without
re-running the search or requiring the user to retype a DOI."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional

from .models import Paper

DEFAULT_SESSION_PATH = ".literature_bot_last_search.json"


def write_last_search(query: str, papers: List[Paper], path: str = DEFAULT_SESSION_PATH) -> None:
    data = {
        "query": query,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "papers": [asdict(p) for p in papers],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_last_search(path: str = DEFAULT_SESSION_PATH) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["papers"] = [Paper(**d) for d in data["papers"]]
    return data


def get_by_ref(path: str, ref: int) -> Optional[Paper]:
    """1-indexed, matching the numbering shown in the search report/console table."""
    data = read_last_search(path)
    if not data:
        return None
    papers = data["papers"]
    if 1 <= ref <= len(papers):
        return papers[ref - 1]
    return None
