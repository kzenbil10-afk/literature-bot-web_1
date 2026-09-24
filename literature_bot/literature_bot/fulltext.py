"""Resolves a real full-text PDF for a paper (not just a link to one), downloads
it, and extracts its text -- so a thesis/article writer gets actual PDF data to
work with instead of having to click through themselves.

Resolution order for a PDF URL:
  1. paper.pdf_url, if a source adapter already gave us one directly (arXiv,
     OpenAlex open-access location, Semantic Scholar openAccessPdf).
  2. Unpaywall (https://unpaywall.org), keyed by DOI -- the standard free
     resolver for open-access full text across the large majority of
     registered DOIs.
  3. The article's own landing page (paper.url): fetch the HTML and read the
     `citation_pdf_url` meta tag, a widely used convention (the same one
     Google Scholar relies on) that DergiPark and most journal platforms set.

Text extraction:
  1. Try the PDF's embedded text layer (pypdf).
  2. If that text looks garbled -- which happens systematically with a lot of
     DergiPark-hosted PDFs, whose embedded fonts remap Turkish glyphs to
     unrelated Unicode codepoints so *every* extractor reads nonsense even
     though the page displays correctly -- fall back to OCR (PyMuPDF page
     rasterization + Tesseract) when Tesseract is installed with the needed
     language packs. Otherwise the (possibly garbled) text-layer output is
     kept, clearly flagged, rather than silently presented as clean.

Every step is best-effort and never raises: a paper we can't get full text
for just gets `fulltext_status="unavailable"` and everything else about it
still works.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests

from .models import Paper

MAX_PDF_BYTES = 40 * 1024 * 1024  # don't download absurdly large files
_LATIN_TR_RE = re.compile(r"[A-Za-zÇĞİIÖŞÜçğıiöşü]")
_GARBLED_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")  # Greek/Coptic block: the telltale sign

# A normal-browser UA for landing pages / PDF downloads (as opposed to the
# self-identifying bot UA used for the metadata APIs in sources/base.py):
# publisher sites are far likelier to serve a PDF to something that looks
# like an actual reader's browser than to an obvious script.
_FETCH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _safe_filename(text: str, max_len: int = 80) -> str:
    """ASCII-only filename (Turkish diacritics folded), so the saved PDF/txt
    files are safe across every filesystem, including on the user's own
    Windows machine, not just the ones that already handle UTF-8 filenames."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\-]+", "_", folded).strip("_")
    return (cleaned or "belge")[:max_len]


# --------------------------------------------------------------------------
# 1) Resolving a PDF URL
# --------------------------------------------------------------------------

def _citation_pdf_url_from_landing_page(url: str, timeout: int = 20) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _FETCH_UA, "Accept": "text/html"},
            timeout=timeout,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    match = re.search(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        resp.text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return urljoin(url, match.group(1))


def _unpaywall_pdf_url(doi: str, email: str, timeout: int = 20) -> Optional[str]:
    try:
        resp = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            headers={"User-Agent": _FETCH_UA},
            timeout=timeout,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not data.get("is_oa"):
        return None
    best = data.get("best_oa_location") or {}
    return best.get("url_for_pdf") or best.get("url")


def resolve_pdf_url(paper: Paper, unpaywall_email: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Returns (pdf_url, method) where method is one of
    "direct" / "unpaywall" / "citation_meta" / None."""
    if paper.pdf_url:
        return paper.pdf_url, "direct"
    if paper.doi and unpaywall_email:
        url = _unpaywall_pdf_url(paper.doi, unpaywall_email)
        if url:
            return url, "unpaywall"
    if paper.url:
        url = _citation_pdf_url_from_landing_page(paper.url)
        if url:
            return url, "citation_meta"
    return None, None


# --------------------------------------------------------------------------
# 2) Downloading
# --------------------------------------------------------------------------

def download_pdf(url: str, dest_path: str, timeout: int = 45) -> bool:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _FETCH_UA, "Accept": "application/pdf,*/*"},
            timeout=timeout,
            stream=True,
        )
    except requests.RequestException:
        return False
    if resp.status_code != 200:
        return False

    total = 0
    chunks = []
    try:
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                return False
            chunks.append(chunk)
    except requests.RequestException:
        return False

    body = b"".join(chunks)
    if not body.startswith(b"%PDF"):
        return False  # not actually a PDF (landing/paywall/HTML error page)

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(body)
    return True


# --------------------------------------------------------------------------
# 3) Text extraction (+ OCR fallback for garbled PDFs)
# --------------------------------------------------------------------------

def _looks_garbled(text: str) -> bool:
    """Detects the specific, common failure mode where a PDF's embedded font
    remaps glyphs to the wrong Unicode block (frequently Greek/Coptic) so every
    text-layer extractor reads nonsense, even though the page renders fine
    visually. Empty text is handled separately by the caller."""
    if not text or len(text) < 40:
        return False
    greek_hits = len(_GARBLED_RE.findall(text))
    letters = len(_LATIN_TR_RE.findall(text)) + greek_hits
    if letters == 0:
        return False
    return (greek_hits / letters) > 0.15


def _extract_text_pypdf(pdf_path: str, max_pages: Optional[int] = None) -> str:
    import pypdf

    reader = pypdf.PdfReader(pdf_path)
    pages = reader.pages[:max_pages] if max_pages else reader.pages
    parts = []
    for page in pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts).strip()


def _ocr_available(lang: str = "tur+eng") -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        import fitz  # noqa: F401  (PyMuPDF)
    except ImportError:
        return False
    try:
        import pytesseract
        langs = set(pytesseract.get_languages(config=""))
        needed = set(lang.split("+"))
        return needed.issubset(langs) or "eng" in langs  # degrade to eng-only if tur pack missing
    except Exception:
        return False


def _extract_text_ocr(pdf_path: str, max_pages: int = 15, dpi: int = 200) -> str:
    import fitz
    import pytesseract
    from PIL import Image
    import io

    doc = fitz.open(pdf_path)
    parts = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            parts.append(pytesseract.image_to_string(img, lang="tur+eng"))
        except Exception:
            try:
                parts.append(pytesseract.image_to_string(img, lang="eng"))
            except Exception:
                continue
    return "\n".join(parts).strip()


def extract_fulltext(pdf_path: str, ocr_max_pages: int = 15) -> dict:
    """Returns {text, method, possibly_garbled, ocr_truncated}."""
    text = ""
    try:
        text = _extract_text_pypdf(pdf_path)
    except Exception:
        text = ""

    garbled = _looks_garbled(text)
    if (not text or garbled) and _ocr_available():
        try:
            import fitz
            page_count = fitz.open(pdf_path).page_count
        except Exception:
            page_count = ocr_max_pages
        ocr_text = _extract_text_ocr(pdf_path, max_pages=ocr_max_pages)
        if ocr_text:
            return {
                "text": ocr_text,
                "method": "ocr",
                "possibly_garbled": False,
                "ocr_truncated": page_count > ocr_max_pages,
            }
    return {
        "text": text,
        "method": "text-layer" if text else "none",
        "possibly_garbled": garbled,
        "ocr_truncated": False,
    }


# --------------------------------------------------------------------------
# 4) Persistent save (explicit, opt-in -- used by `save --download`)
# --------------------------------------------------------------------------

def save_one_fulltext(
    p: Paper,
    out_dir: str,
    unpaywall_email: Optional[str] = None,
    ocr_max_pages: int = 15,
    timeout: int = 45,
) -> None:
    """Downloads and extracts the full text for a SINGLE paper, permanently,
    into `out_dir`. Mutates `p.fulltext_*` in place. Never raises."""
    try:
        url, method = resolve_pdf_url(p, unpaywall_email)
        if not url:
            p.fulltext_status = "unavailable"
            p.fulltext_error = "PDF bağlantısı bulunamadı (ne doğrudan link, ne Unpaywall, ne citation_pdf_url)"
            return

        filename = _safe_filename(f"{p.cite_key()}_{p.title}", max_len=90) + ".pdf"
        dest_path = os.path.join(out_dir, filename)
        ok = download_pdf(url, dest_path, timeout=timeout)
        if not ok:
            p.fulltext_status = "unavailable"
            p.fulltext_error = f"PDF indirilemedi ({method} kaynağından: {url})"
            return

        p.fulltext_pdf_path = dest_path
        p.fulltext_source_url = url
        p.fulltext_source_method = method

        result = extract_fulltext(dest_path, ocr_max_pages=ocr_max_pages)
        p.fulltext_method = result["method"]
        p.fulltext_possibly_garbled = result["possibly_garbled"]
        text = result["text"]
        if text:
            txt_path = os.path.splitext(dest_path)[0] + ".txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            p.fulltext_text_path = txt_path
            p.fulltext_chars = len(text)
            p.fulltext_status = "ok"
        else:
            p.fulltext_status = "pdf_only"  # got the PDF, couldn't extract usable text
    except Exception as e:
        p.fulltext_status = "unavailable"
        p.fulltext_error = f"beklenmeyen hata: {e}"


def fetch_fulltexts(
    papers: List[Paper],
    out_dir: str = "tam_metinler",
    max_count: int = 15,
    unpaywall_email: Optional[str] = None,
    ocr_max_pages: int = 15,
    timeout: int = 45,
    max_workers: int = 4,
) -> dict:
    """Batch version of save_one_fulltext -- used when `save`-ing several refs
    at once with --download. Fills in paper.fulltext_* fields in place for up
    to `max_count` papers. Never raises."""
    targets = papers[:max_count]
    status = {"attempted": len(targets), "downloaded": 0, "ocr_used": 0, "failed": 0}
    if not targets:
        return status

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(save_one_fulltext, p, out_dir, unpaywall_email, ocr_max_pages, timeout): p
            for p in targets
        }
        for fut in as_completed(futures):
            p = futures[fut]
            fut.result()  # save_one_fulltext never raises
            if p.fulltext_status in ("ok", "pdf_only"):
                status["downloaded"] += 1
                if p.fulltext_method == "ocr":
                    status["ocr_used"] += 1
            else:
                status["failed"] += 1

    return status


# --------------------------------------------------------------------------
# 5) Ephemeral preview (default in `search --preview-fulltext` -- nothing is
#    kept on disk; only a short excerpt is returned for display)
# --------------------------------------------------------------------------

def preview_one_fulltext(
    p: Paper,
    unpaywall_email: Optional[str] = None,
    preview_chars: int = 1200,
    ocr_max_pages: int = 5,
    timeout: int = 45,
) -> None:
    """Resolves and downloads the PDF to a throwaway temp file just long enough
    to extract a short preview, then deletes it. Mutates `p.preview_*` in
    place; never touches `p.fulltext_*` and never raises."""
    tmp_dir = None
    try:
        url, method = resolve_pdf_url(p, unpaywall_email)
        if not url:
            p.preview_available = False
            p.preview_reason = "PDF bağlantısı bulunamadı"
            return

        tmp_dir = tempfile.mkdtemp(prefix="litbot_preview_")
        tmp_path = os.path.join(tmp_dir, "preview.pdf")
        if not download_pdf(url, tmp_path, timeout=timeout):
            p.preview_available = False
            p.preview_reason = f"PDF indirilemedi ({method} kaynağından)"
            return

        p.preview_source_method = method
        result = extract_fulltext(tmp_path, ocr_max_pages=ocr_max_pages)
        text = result["text"]
        if not text:
            p.preview_available = False
            p.preview_reason = "PDF indirildi ama metin çıkarılamadı"
            return

        p.preview_available = True
        p.preview_method = result["method"]
        p.preview_text = text[:preview_chars].strip()
        if result["possibly_garbled"]:
            p.preview_reason = "metin bozuk çıkmış olabilir (OCR mevcut değil)"
    except Exception as e:
        p.preview_available = False
        p.preview_reason = f"beklenmeyen hata: {e}"
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def preview_fulltexts(
    papers: List[Paper],
    max_count: int = 5,
    unpaywall_email: Optional[str] = None,
    preview_chars: int = 1200,
    ocr_max_pages: int = 5,
    timeout: int = 45,
    max_workers: int = 4,
) -> dict:
    """Batch version of preview_one_fulltext for the top `max_count` (already-
    ranked) papers. Nothing is persisted to disk -- purely for on-screen/report
    preview so the user can decide what's actually worth `save --download`-ing."""
    targets = papers[:max_count]
    status = {"attempted": len(targets), "available": 0}
    if not targets:
        return status

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(preview_one_fulltext, p, unpaywall_email, preview_chars, ocr_max_pages, timeout)
            for p in targets
        ]
        for fut in as_completed(futures):
            fut.result()  # never raises

    status["available"] = sum(1 for p in targets if p.preview_available)
    return status
