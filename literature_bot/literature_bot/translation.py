"""Automatic translation of non-Turkish titles/abstracts into Turkish, so a
result list dominated by English-language papers (the norm for OpenAlex,
Crossref, Semantic Scholar, arXiv...) is readable at a glance in Turkish.

Important: translations are a *reading aid only*. The original title is
always what goes into the APA reference and the BibTeX entry — you cite the
paper as it was actually published, never a machine-translated title.

Several engines are supported:
  - "claude" / "nvidia" / "llm": one batched LLM API call for the whole result
    set. Best quality. "claude" uses ANTHROPIC_API_KEY, "nvidia" uses
    NVIDIA_API_KEY (see literature_bot/llm_client.py for how the provider and
    model are picked); "llm" / "auto" just use whichever one is configured.
    Reuses the same key/provider as --deep-research / draft.
  - "mymemory" / "google": free, keyless engines via the `deep-translator`
    package. No signup needed, but they are unofficial/rate-limited services —
    fine for an occasional run, not guaranteed for heavy batch use, and may be
    flaky from a shared/cloud IP address.
"""
from __future__ import annotations

import json
import re
import time
from typing import List, Optional

from . import llm_client
from .models import Paper

_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
_TR_MARKERS = (
    " ve ", " ile ", " için ", " bir ", " bu ", " olan ", " olarak ", " üzerine ",
    " arasında ", " göre ", " gibi ", " değil", " mi ", " mu ", " sonuç", " çalışma",
    " araştırma", " yöntem", " veri",
)


def looks_turkish(text: Optional[str]) -> bool:
    """Cheap heuristic so we don't re-translate text that's already Turkish
    (common for Turkish-authored work indexed in these APIs) without pulling
    in a heavyweight language-detection dependency."""
    if not text or not text.strip():
        return True  # nothing to translate
    lowered = f" {text.lower()} "
    marker_hits = sum(1 for m in _TR_MARKERS if m in lowered)
    has_tr_chars = any(ch in _TR_CHARS for ch in text)
    return marker_hits >= 2 or (has_tr_chars and marker_hits >= 1)


_EN_STOPWORDS = (
    " the ", " and ", " of ", " in ", " is ", " are ", " this ", " that ", " with ",
    " for ", " on ", " was ", " were ", " to ", " by ", " we ", " study ", " results ",
)


def _looks_english(text: str) -> bool:
    """MyMemoryTranslator needs an explicit source language and can't auto-detect,
    so we only ever hand it text that plausibly *is* English -- otherwise it will
    silently mistranslate (e.g. treat a French abstract as English and mangle it)
    instead of failing loudly. Non-English/non-Turkish text should go through
    "google" (which auto-detects) or be left untranslated."""
    lowered = f" {text.lower()} "
    return sum(1 for w in _EN_STOPWORDS if w in lowered) >= 3


def _translate_batch_llm(
    texts: List[str], provider: Optional[str], api_key: Optional[str], model: Optional[str]
) -> Optional[List[str]]:
    if not texts:
        return []

    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))
    prompt = (
        "Aşağıda numaralandırılmış akademik başlık/özet metinleri var (çoğunlukla İngilizce). "
        "Her birini akıcı, akademik bir Türkçeye çevir. Metin zaten Türkçeyse aynen koru. "
        "SADECE şu JSON formatında yanıt ver, başka hiçbir açıklama, giriş veya kod bloğu ekleme:\n"
        '{"translations": ["...", "...", ...]}\n'
        f"Liste, giriş sayısıyla birebir aynı sırada ve aynı uzunlukta olmalı ({len(texts)} öğe).\n\n"
        f"{numbered}"
    )
    raw = llm_client.chat_complete(prompt, model=model, max_tokens=6000, api_key=api_key, provider=provider)
    if not raw:
        return None
    try:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        translations = data.get("translations")
        if isinstance(translations, list) and len(translations) == len(texts):
            return [str(t) for t in translations]
        return None
    except Exception:
        return None


def _translate_one_free(text: str, engine: str, max_chars: int = 450) -> Optional[str]:
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except ImportError:
        return None
    try:
        if engine == "mymemory":
            # MyMemory needs an explicit source language (no auto-detect), so it's only
            # safe to use on text that plausibly *is* English -- otherwise skip rather
            # than mistranslate (see _looks_english). Non-English/non-Turkish abstracts
            # should be caught by "google" earlier in the chain instead.
            if not _looks_english(text):
                return None
            # Free tier has a short per-request character limit; chunk long abstracts.
            chunks = [text[i:i + max_chars] for i in range(0, len(text), max_chars)] or [text]
            out = []
            for c in chunks:
                out.append(MyMemoryTranslator(source="en-GB", target="tr-TR").translate(c))
                time.sleep(0.3)
            joined = " ".join(o for o in out if o)
            return joined or None
        if engine == "google":
            return GoogleTranslator(source="auto", target="tr").translate(text)
    except Exception:
        return None
    return None


def _translate_one_free_chain(text: str, engines: List[str], max_chars: int = 450) -> "tuple[Optional[str], Optional[str]]":
    """Try each free engine in order, return (translation, engine_that_succeeded)."""
    for eng in engines:
        result = _translate_one_free(text, eng, max_chars=max_chars)
        if result:
            return result, eng
    return None, None


def translate_papers(
    papers: List[Paper],
    engine: str = "auto",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    abstract_char_limit: int = 700,
) -> dict:
    """Fills `paper.title_tr` / `paper.abstract_tr` in place for every paper
    whose text isn't already Turkish. Never raises — a translation failure
    just leaves those fields empty so the report still builds.

    `engine`: "auto" (LLM if one is configured, else free engines), "claude"
    / "nvidia" / "llm" (force an LLM call -- "claude"/"nvidia" also pin the
    provider), "mymemory", "google", or "none".

    Returns a small status dict used for the CLI's progress line.
    """
    forced_provider = provider
    if engine == "claude":
        forced_provider = forced_provider or "anthropic"
    elif engine == "openai":
        forced_provider = forced_provider or "openai"
    elif engine == "nvidia":
        forced_provider = forced_provider or "nvidia"
    resolved_provider = llm_client.detect_provider(forced_provider)

    to_translate = [
        p for p in papers
        if not looks_turkish(p.title) or (p.abstract and not looks_turkish(p.abstract))
    ]
    status = {
        "engine_used": None,
        "translated": 0,
        "failed": 0,
        "skipped_already_tr": len(papers) - len(to_translate),
        "total_considered": len(to_translate),
    }
    if not to_translate:
        return status

    chosen = engine
    if engine == "auto":
        chosen = "llm" if resolved_provider else "auto_free"
    elif engine in ("claude", "openai", "nvidia"):
        chosen = "llm"

    if chosen == "llm" and resolved_provider:
        titles = [p.title for p in to_translate]
        abstracts = [(p.abstract or "")[:abstract_char_limit] for p in to_translate]
        results = _translate_batch_llm(
            titles + abstracts, provider=resolved_provider, api_key=api_key, model=model,
        )
        if results is not None:
            n = len(to_translate)
            for p, t_title, t_abs in zip(to_translate, results[:n], results[n:]):
                p.title_tr = t_title.strip() if not looks_turkish(p.title) else None
                p.abstract_tr = t_abs.strip() if (p.abstract and not looks_turkish(p.abstract)) else None
                status["translated"] += 1
            status["engine_used"] = resolved_provider
            return status
        # LLM call failed (no package / bad key / API error) -> fall back to free engines.
        chosen = "auto_free"
        status["engine_used"] = None

    if chosen in ("mymemory", "google", "auto_free"):
        # "auto_free" tries Google first (auto-detects source language, so it also handles
        # non-English/non-Turkish abstracts correctly) and falls back to MyMemory (assumes
        # English) only where Google didn't work. An explicit --translate-engine choice is
        # honored as a single engine instead.
        engine_chain = ["google", "mymemory"] if chosen == "auto_free" else [chosen]
        engines_seen = set()
        any_ok = False
        for p in to_translate:
            ok = True
            if not looks_turkish(p.title):
                t, used = _translate_one_free_chain(p.title, engine_chain)
                if t:
                    p.title_tr = t
                    any_ok = True
                    engines_seen.add(used)
                else:
                    ok = False
            if p.abstract and not looks_turkish(p.abstract):
                t, used = _translate_one_free_chain(p.abstract[:abstract_char_limit], engine_chain)
                if t:
                    p.abstract_tr = t
                    any_ok = True
                    engines_seen.add(used)
                else:
                    ok = False
            if ok:
                status["translated"] += 1
            else:
                status["failed"] += 1
            time.sleep(0.25)  # be polite to the free/keyless endpoint
        if status["engine_used"] is None:
            status["engine_used"] = "+".join(sorted(engines_seen)) if any_ok else None

    return status
