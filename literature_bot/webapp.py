"""Flask web application for literature_bot.

This is the "gerçek internet tabanlı yazılım" version of the tool: a single
Flask process that serves both a small JSON API (wrapping the exact same
search/translation/fulltext/synthesis logic the CLI uses) and a mobile-
friendly static frontend (static/index.html), so it's reachable from any
browser -- desktop or phone -- once deployed, with no local install needed
by the end user at all.

Differences from the CLI (literature_bot/cli.py), by design:

  - No server-side "last search" session file. A search's full results are
    returned to the browser as JSON and the browser holds them (in memory /
    localStorage) for the rest of that visit -- this also means the API is
    safely stateless across multiple server processes/workers, which the
    CLI's file-based session_cache.py was never designed for.

  - The library is stored via literature_bot/storage.py (Turso when
    configured, else a local sqlite file for local testing) instead of
    library.py's always-local-sqlite3 file, so saved sources survive a
    redeploy on a free host with an ephemeral filesystem.

  - `save --download`'s extracted text is stored *inline* in the saved
    paper's own JSON (Paper.fulltext_text_inline) instead of as a path to a
    file on disk, for the same persistence reason. The downloaded PDF binary
    itself is not kept -- only its extracted text -- a deliberate trade-off
    for free hosting (the original can always be re-fetched from its source
    URL/DOI).

  - All API keys (LLM provider, Unpaywall/OpenAlex/etc.) are read from
    server-side environment variables only -- never sent by or exposed to
    the browser.
"""
from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory

from literature_bot import llm_client, storage
from literature_bot.citations import bibliography_bibtex, format_apa
from literature_bot.fulltext import (
    preview_one_fulltext,
    resolve_pdf_url,
    save_one_fulltext,
)
from literature_bot.models import Paper
from literature_bot.ranking import sort_papers
from literature_bot.search import run_search
from literature_bot.sources import ALL_SOURCES
from literature_bot.synthesis import (
    deep_research_synthesis,
    generate_draft,
    template_draft,
)
from literature_bot.translation import translate_papers

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")


def _ensure_dergipark_cache() -> None:
    """The DergiPark index (dergipark_cache.sqlite3, ~28MB) is too big for
    GitHub's browser-based "Upload files" drag-and-drop (25MB/file cap), so
    the repo ships a gzip-compressed copy (dergipark_cache.sqlite3.gz,
    ~10MB) instead. Decompress it once per process start, if the plain
    .sqlite3 file isn't already sitting there -- cheap (~1s), and safe to
    redo on every restart since it's read-only reference data, not
    something that needs to persist."""
    db_path = os.environ.get("DERGIPARK_DB", "dergipark_cache.sqlite3")
    gz_path = db_path + ".gz"
    if os.path.exists(db_path) or not os.path.exists(gz_path):
        return
    try:
        with gzip.open(gz_path, "rb") as f_in, open(db_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    except OSError:
        pass  # DergiPark search will just come back empty; nothing else breaks.


_ensure_dergipark_cache()

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

_SOURCE_LABELS_TR = {
    "openalex": "OpenAlex",
    "crossref": "Crossref",
    "arxiv": "arXiv",
    "semanticscholar": "Semantic Scholar",
    "pubmed": "PubMed",
    "dergipark": "DergiPark",
}

APP_PASSWORD = os.environ.get("APP_PASSWORD")


# ---------------------------------------------------------------------------
# optional shared-password gate (off unless APP_PASSWORD is set server-side)
# ---------------------------------------------------------------------------

@app.before_request
def _check_password():
    if not APP_PASSWORD:
        return None
    if not request.path.startswith("/api/"):
        return None
    if request.path == "/api/health":
        return None
    supplied = request.headers.get("X-App-Password", "")
    if supplied != APP_PASSWORD:
        return jsonify({"error": "unauthorized", "message": "Geçersiz veya eksik şifre"}), 401
    return None


def _json_errors(fn):
    """Every endpoint below is best-effort user-facing: on an unexpected
    exception, return a clean JSON 500 instead of an HTML stack trace page,
    and log the real traceback server-side for debugging."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return jsonify({"error": "server_error", "message": str(e)}), 500

    return wrapper


def _paper_out(p: Paper, full_text: bool = False) -> dict:
    """Paper -> JSON-safe dict for API responses. By default the (possibly
    large) inline full text is summarized to its length only, to keep list
    responses small; pass full_text=True for single-item endpoints that
    actually need the body (e.g. viewing one saved source)."""
    from dataclasses import asdict

    d = asdict(p)
    if not full_text:
        d["fulltext_text_inline"] = None
    return d


# ---------------------------------------------------------------------------
# static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ---------------------------------------------------------------------------
# health / config info
# ---------------------------------------------------------------------------

@app.route("/api/health")
@_json_errors
def health():
    provider = llm_client.detect_provider(None)
    return jsonify(
        {
            "ok": True,
            "storage": storage.backend_name(),
            "llm_provider": provider,
            "llm_model": llm_client.default_model(provider) if provider else None,
            "password_protected": bool(APP_PASSWORD),
            "sources": [{"id": s, "label": _SOURCE_LABELS_TR.get(s, s)} for s in ALL_SOURCES],
        }
    )


# ---------------------------------------------------------------------------
# search (nothing persisted)
# ---------------------------------------------------------------------------

@app.route("/api/search", methods=["POST"])
@_json_errors
def api_search():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "bad_request", "message": "query boş olamaz"}), 400

    sources = body.get("sources") or list(ALL_SOURCES)
    if isinstance(sources, str):
        sources = [s.strip() for s in sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        return jsonify({"error": "bad_request", "message": f"Bilinmeyen kaynak(lar): {unknown}"}), 400

    limit_per_source = int(body.get("limit_per_source") or 20)
    max_results = int(body.get("max_results") or 40)
    year_min = body.get("year_min")
    year_max = body.get("year_max")
    sort_by = body.get("sort") or "relevance"
    do_translate = bool(body.get("translate", True))
    do_deep_research = bool(body.get("deep_research", False))
    language = body.get("language") or "tr"

    dergipark_db = os.environ.get("DERGIPARK_DB", "dergipark_cache.sqlite3")

    ranked, counts, raw_total = run_search(
        query=query,
        source_names=sources,
        limit_per_source=limit_per_source,
        year_min=int(year_min) if year_min else None,
        year_max=int(year_max) if year_max else None,
        openalex_email=os.environ.get("OPENALEX_EMAIL"),
        s2_api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
        pubmed_api_key=os.environ.get("PUBMED_API_KEY"),
        dergipark_db=dergipark_db,
    )
    ranked = sort_papers(ranked, by=sort_by)[:max_results]

    # translate_papers() and deep_research_synthesis() each make their own
    # independent NVIDIA/Claude call, and NVIDIA's free tier can take up to
    # ~90s (bounded retries) per call when it's being slow. They don't depend
    # on each other's output (translation writes title_tr/abstract_tr; deep
    # synthesis only reads the original title/abstract), so run them
    # concurrently instead of back-to-back -- worst case is now ~90s total
    # instead of ~180s.
    translation_status = None
    deep_synthesis = None
    jobs = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        if do_translate:
            jobs["translate"] = executor.submit(translate_papers, ranked)
        if do_deep_research:
            jobs["deep"] = executor.submit(deep_research_synthesis, query=query, papers=ranked, language=language)
        if "translate" in jobs:
            translation_status = jobs["translate"].result()
        if "deep" in jobs:
            deep_synthesis = jobs["deep"].result()

    return jsonify(
        {
            "query": query,
            "counts": counts,
            "raw_total": raw_total,
            "unique_total": len(ranked),
            "translation_status": translation_status,
            "deep_synthesis": deep_synthesis,
            "papers": [_paper_out(p) for p in ranked],
            "dergipark_warning": (
                "dergipark" in sources and not os.path.exists(dergipark_db)
            ),
        }
    )


# ---------------------------------------------------------------------------
# on-demand single-paper full-text preview (nothing persisted)
# ---------------------------------------------------------------------------

@app.route("/api/preview", methods=["POST"])
@_json_errors
def api_preview():
    body = request.get_json(force=True, silent=True) or {}
    paper = Paper.from_dict(body.get("paper") or {})
    preview_one_fulltext(
        paper,
        unpaywall_email=os.environ.get("UNPAYWALL_EMAIL"),
        preview_chars=int(body.get("preview_chars") or 1500),
        ocr_max_pages=int(body.get("ocr_max_pages") or 5),
    )
    return jsonify({"paper": _paper_out(paper)})


@app.route("/api/resolve-pdf", methods=["POST"])
@_json_errors
def api_resolve_pdf():
    body = request.get_json(force=True, silent=True) or {}
    paper = Paper.from_dict(body.get("paper") or {})
    url, method = resolve_pdf_url(paper, unpaywall_email=os.environ.get("UNPAYWALL_EMAIL"))
    return jsonify({"pdf_url": url, "method": method})


# ---------------------------------------------------------------------------
# save (persists to the library)
# ---------------------------------------------------------------------------

@app.route("/api/save", methods=["POST"])
@_json_errors
def api_save():
    body = request.get_json(force=True, silent=True) or {}
    paper = Paper.from_dict(body.get("paper") or {})
    if not paper.title:
        return jsonify({"error": "bad_request", "message": "geçersiz kaynak (başlık yok)"}), 400

    collection = (body.get("collection") or "genel").strip() or "genel"
    download = bool(body.get("download", False))

    if download:
        tmp_dir = tempfile.mkdtemp(prefix="litbot_save_")
        try:
            save_one_fulltext(
                paper,
                out_dir=tmp_dir,
                unpaywall_email=os.environ.get("UNPAYWALL_EMAIL"),
                ocr_max_pages=15,
            )
            # Pull the extracted text (if any) inline, then drop the local
            # paths -- they point into a scratch dir on THIS server process
            # and won't mean anything after it restarts.
            if paper.fulltext_text_path and os.path.exists(paper.fulltext_text_path):
                with open(paper.fulltext_text_path, "r", encoding="utf-8") as f:
                    paper.fulltext_text_inline = f.read()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        paper.fulltext_pdf_path = None
        paper.fulltext_text_path = None

    backend = storage.get_backend()
    saved_id = backend.save_paper(paper, collection)
    return jsonify({"id": saved_id, "collection": collection, "fulltext_status": paper.fulltext_status})


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------

@app.route("/api/collections")
@_json_errors
def api_collections():
    return jsonify({"collections": storage.get_backend().list_collections()})


@app.route("/api/library")
@_json_errors
def api_library():
    collection = request.args.get("collection") or None
    backend = storage.get_backend()
    entries = backend.list_papers(collection=collection)
    return jsonify(
        {
            "entries": [
                {"id": e["id"], "collection": e["collection"], "saved_at": e["saved_at"], "paper": _paper_out(e["paper"])}
                for e in entries
            ]
        }
    )


@app.route("/api/library/<int:saved_id>")
@_json_errors
def api_library_item(saved_id: int):
    entry = storage.get_backend().get_paper(saved_id)
    if not entry:
        return jsonify({"error": "not_found"}), 404
    return jsonify(
        {"id": entry["id"], "collection": entry["collection"], "saved_at": entry["saved_at"], "paper": _paper_out(entry["paper"], full_text=True)}
    )


@app.route("/api/library/<int:saved_id>", methods=["DELETE"])
@_json_errors
def api_library_delete(saved_id: int):
    ok = storage.get_backend().remove_paper(saved_id)
    return jsonify({"ok": ok})


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------

@app.route("/api/draft", methods=["POST"])
@_json_errors
def api_draft():
    body = request.get_json(force=True, silent=True) or {}
    collection = body.get("collection") or None
    doc_type = body.get("doc_type") or "article"
    language = body.get("language") or "tr"

    backend = storage.get_backend()
    entries = backend.list_papers(collection=collection)
    if not entries:
        return jsonify({"error": "bad_request", "message": "Bu koleksiyonda/kütüphanede kayıtlı kaynak yok"}), 400

    papers = [e["paper"] for e in entries]
    title = body.get("title") or (f"{collection.capitalize()} Taslağı" if collection else "Literatür Taslağı")

    draft_text = generate_draft(title=title, papers=papers, doc_type=doc_type, language=language)
    used_llm = draft_text is not None
    if draft_text is None:
        draft_text = template_draft(title, papers, doc_type=doc_type)
    else:
        draft_text = f"# {title}\n\n{draft_text}"

    ordered = sorted(papers, key=lambda p: (p.first_author_surname().lower(), p.year or 0))
    bib_lines = ["## Kaynakça", ""] + [f"- {format_apa(p)}" for p in ordered]
    draft_text = draft_text.rstrip() + "\n\n" + "\n".join(bib_lines) + "\n"
    bibtex = bibliography_bibtex(ordered)

    return jsonify(
        {
            "title": title,
            "used_llm": used_llm,
            "n_sources": len(papers),
            "n_with_fulltext": sum(1 for p in papers if p.fulltext_status == "ok"),
            "draft_markdown": draft_text,
            "bibtex": bibtex,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
