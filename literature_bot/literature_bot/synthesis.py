"""Turns a ranked reading list into an actual literature review:
1) rule-based thematic grouping (always available, no extra dependency), and
2) optional LLM-based deep synthesis when an LLM provider is configured
   (Claude via ANTHROPIC_API_KEY, or NVIDIA NIM via NVIDIA_API_KEY -- see
   llm_client.py).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from . import llm_client
from .models import Paper

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "is", "are",
    "this", "that", "we", "our", "study", "paper", "results", "using", "based", "from",
    "ve", "veya", "ile", "için", "bir", "bu", "da", "de", "çalışma", "sonuç", "sonuçlar",
    "üzerine", "göre", "olan", "olarak", "gibi",
}


def _keywords(text: str) -> List[str]:
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{4,}", (text or "").lower())
    return [w for w in words if w not in _STOPWORDS]


def build_theme_clusters(papers: List[Paper], n_themes: int = 5) -> Dict[str, List[Paper]]:
    """Group papers under the top recurring keywords found in their titles/abstracts.
    Cheap, dependency-free stand-in for topic modelling — good enough to structure
    a reading list into sections."""
    counter: Counter = Counter()
    for p in papers:
        text = f"{p.title} {p.abstract or ''}"
        counter.update(set(_keywords(text)))

    top_keywords = [w for w, _ in counter.most_common(n_themes * 3)]
    # keep keywords that are reasonably distinctive (appear in >=2 papers, <80% of papers)
    n = max(len(papers), 1)
    top_keywords = [w for w in top_keywords if 2 <= counter[w] <= 0.8 * n][:n_themes]

    clusters: Dict[str, List[Paper]] = defaultdict(list)
    used_ids = set()
    for kw in top_keywords:
        for p in papers:
            text = f"{p.title} {p.abstract or ''}".lower()
            if kw in text and id(p) not in used_ids:
                clusters[kw].append(p)
                used_ids.add(id(p))

    leftovers = [p for p in papers if id(p) not in used_ids]
    if leftovers:
        clusters["Diğer / genel kaynaklar"] = leftovers

    return dict(clusters)


def extractive_summary(papers: List[Paper], max_sentences: int = 1) -> str:
    """Fallback synthesis with no LLM: one representative sentence per top paper."""
    lines = []
    for p in papers[:10]:
        if not p.abstract:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", p.abstract.strip())
        snippet = " ".join(sentences[:max_sentences])
        author = p.first_author_surname()
        lines.append(f"- **{author} ({p.year or 't.y.'})**: {snippet}")
    return "\n".join(lines) if lines else "_Özet metni bulunan yeterli kaynak yok._"


def deep_research_synthesis(
    query: str,
    papers: List[Paper],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    language: str = "tr",
) -> Optional[str]:
    """Ask an LLM (Claude or NVIDIA NIM -- see llm_client.py) to write an
    actual synthesized literature-review narrative: themes,
    agreements/contradictions between studies, and gaps — citing papers by
    (Author, Year) so it matches the generated bibliography.

    Returns None (never raises) if no provider is configured or the call
    fails, so callers can transparently fall back to `extractive_summary`.
    """
    if not llm_client.is_configured(provider):
        return None

    refs = []
    for p in papers[:40]:
        refs.append(
            f"- ({p.first_author_surname()}, {p.year or 't.y.'}) {p.title} — "
            f"{(p.abstract or 'Özet yok.')[:600]}"
        )
    refs_text = "\n".join(refs)

    lang_instruction = (
        "Yanıtı Türkçe yaz, akademik ve tez/makale yazımına uygun bir üslup kullan."
        if language == "tr"
        else "Write the response in academic English suitable for a thesis/paper."
    )

    prompt = f"""Sen bir akademik literatür taraması asistanısın. Aşağıda "{query}" konusu için
toplanmış kaynakların listesi (yazar, yıl ve özet) verilmiştir.

{refs_text}

Görevin:
1. Bu kaynakları 3-6 tematik başlık altında grupla ve her tema için kaynakları (Yazar, Yıl)
   formatında atıfta bulunarak sentezleyen kısa bir paragraf yaz.
2. Kaynaklar arasındaki ortak bulguları, çelişkileri veya metodolojik farklılıkları belirt.
3. Literatürdeki boşlukları (research gaps) ve olası gelecek araştırma yönlerini listele.
4. {lang_instruction}
5. Sadece verilen kaynaklara dayan; listede olmayan kaynak icat etme.

Markdown başlıkları kullanarak yapılandırılmış bir çıktı üret (## Tematik Sentez, ## Ortak
Bulgular ve Çelişkiler, ## Araştırma Boşlukları ve Öneriler)."""

    return llm_client.chat_complete(prompt, model=model, max_tokens=3000, api_key=api_key, provider=provider)


def _paper_source_block(p: Paper, idx: int, max_chars: int = 4000) -> str:
    """One reference's worth of material for the draft prompt: full text when
    it was actually downloaded and saved (`save --download`), otherwise just
    the abstract. Labelled with an index so the model's citations are easy to
    cross-check against the bibliography built from the same list/order."""
    if p.fulltext_status in ("ok",) and p.fulltext_chars:
        if p.fulltext_text_inline:
            # web app path: the extracted text is stored inline in the paper's
            # own JSON (see models.Paper.fulltext_text_inline), not on disk.
            body = p.fulltext_text_inline[:max_chars]
            kind = "TAM METİN (parça)"
        else:
            try:
                with open(p.fulltext_text_path, "r", encoding="utf-8") as f:
                    body = f.read()[:max_chars]
                kind = "TAM METİN (parça)"
            except (OSError, TypeError):
                body = p.abstract or "Özet yok."
                kind = "ÖZET"
    else:
        body = (p.abstract or "Özet yok.")[:max_chars]
        kind = "ÖZET"
    return (
        f"[{idx}] ({p.first_author_surname()}, {p.year or 't.y.'}) {p.title}\n"
        f"{kind}: {body}"
    )


_DRAFT_SECTIONS = {
    "article": (
        "## Öz\n## Giriş\n## Literatür Taraması\n## Tartışma\n## Sonuç"
    ),
    "thesis": (
        "## Özet\n## 1. Giriş\n### 1.1 Problem Durumu\n### 1.2 Araştırmanın Amacı ve Önemi\n"
        "## 2. Literatür Taraması\n## 3. Tartışma\n## 4. Sonuç ve Öneriler"
    ),
}


def generate_draft(
    title: str,
    papers: List[Paper],
    doc_type: str = "article",
    language: str = "tr",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    max_source_chars: int = 4000,
) -> Optional[str]:
    """Synthesizes a saved-paper library (or a collection within it) into an
    actual structured draft -- not just a literature-review paragraph, but a
    full article/thesis skeleton with real prose in each section, built only
    from the given sources and citing them as (Yazar, Yıl).

    Uses full text when a paper has one (`save --download`'d), falling back to
    its abstract otherwise -- so the more the user has actually downloaded,
    the richer the draft. Returns None (never raises) if no LLM provider is
    configured (see llm_client.py); callers should fall back to
    `template_draft` in that case.
    """
    if not llm_client.is_configured(provider):
        return None

    blocks = [_paper_source_block(p, i, max_source_chars) for i, p in enumerate(papers, 1)]
    sources_text = "\n\n".join(blocks)

    lang_instruction = (
        "Tamamını akademik Türkçe yaz, tez/makale yazım diline uygun, resmi ve akıcı bir üslup kullan."
        if language == "tr"
        else "Write the whole thing in formal academic English suitable for a thesis/article."
    )
    section_outline = _DRAFT_SECTIONS.get(doc_type, _DRAFT_SECTIONS["article"])
    doc_label = "bir tez bölümü/taslağı" if doc_type == "thesis" else "bir makale taslağı"

    prompt = f"""Sen deneyimli bir akademik yazardan yardım isteyen bir araştırmacıya
"{title}" başlığı/konusu üzerine {doc_label} yazmasında yardımcı oluyorsun.

Aşağıda araştırmacının bizzat seçip kaydettiği kaynaklar listelenmiştir (numaralı,
yazar/yıl ve tam metin ya da özetleriyle). Bu taslağı YALNIZCA bu kaynaklara
dayanarak yaz -- listede olmayan hiçbir kaynağı icat etme, hiçbir istatistik veya
alıntıyı uydurma.

KAYNAKLAR:
{sources_text}

GÖREV:
Aşağıdaki bölüm yapısını kullanarak akıcı, iyi sentezlenmiş, gerçek akademik nesir
(sadece madde işaretleri değil) içeren tam bir taslak yaz:

{section_outline}

Kurallar:
1. Literatür Taraması / ilgili bölümde kaynakları tek tek özetlemek yerine TEMALARA göre
   sentezle: hangi kaynaklar hangi konuda hemfikir, hangileri çelişiyor, hangi yöntemsel
   farklılıklar var -- bunları birbirine bağlı bir anlatı olarak yaz.
2. Her iddiayı (Yazar, Yıl) formatında kaynağa bağla; kaynak numaralarını değil yazar-yıl
   formatını kullan (APA tarzı metin içi atıf).
3. Giriş bölümünde konunun önemini ve taslağın kapsamını kısaca çerçevele.
4. Tartışma/Sonuç bölümünde kaynaklardan çıkan ortak bulguları, boşlukları ve olası
   gelecek araştırma yönlerini belirt.
5. Bu bir TASLAKTIR; araştırmacının kendi katkısı, özgün bulguları veya yöntem bölümü
   detayları senin elinde değil -- bu kısımlarda ne gerektiğini kısa bir [YAZAR NOTU: ...]
   köşeli parantez notuyla belirt, uydurma bir içerik ekleme.
6. {lang_instruction}

Markdown başlıklarını yukarıdaki yapıya birebir uyacak şekilde kullan."""

    return llm_client.chat_complete(prompt, model=model, max_tokens=8000, api_key=api_key, provider=provider)


def template_draft(title: str, papers: List[Paper], doc_type: str = "article", n_themes: int = 5) -> str:
    """No-LLM fallback: a real section skeleton filled with the rule-based
    thematic grouping + extractive summary, clearly labeled as a starting
    point rather than a finished synthesis. Never empty, never raises."""
    clusters = build_theme_clusters(papers, n_themes=n_themes)
    lines = [f"# {title}", ""]
    lines.append(
        "_Bu taslak, LLM tabanlı sentez olmadan kural tabanlı gruplama ile oluşturulmuştur "
        "(ne ANTHROPIC_API_KEY ne de NVIDIA_API_KEY tanımlıydı, ya da tanımlı olan sağlayıcıya "
        "yapılan çağrı bu seferlik başarısız oldu -- ücretsiz LLM uçları zaman zaman yanıt "
        "vermeyebilir). Gerçek akıcı bir sentez için birkaç dakika sonra tekrar deneyin._"
    )
    lines.append("")
    lines.append("## Öz" if doc_type == "article" else "## Özet")
    lines.append("[YAZAR NOTU: Öz/özet, taslak tamamlandıktan sonra yazılmalıdır.]")
    lines.append("")
    lines.append("## Giriş")
    lines.append(f"[YAZAR NOTU: '{title}' konusunun önemini ve bu çalışmanın kapsamını burada çerçeveleyin.]")
    lines.append("")
    lines.append("## Literatür Taraması")
    lines.append("")
    for theme, theme_papers in clusters.items():
        lines.append(f"### {theme.capitalize()}")
        lines.append("")
        lines.append(extractive_summary(theme_papers, max_sentences=2))
        lines.append("")
    lines.append("## Tartışma")
    lines.append("[YAZAR NOTU: Kaynaklar arası ortak bulgular, çelişkiler ve boşluklar burada tartışılmalıdır.]")
    lines.append("")
    lines.append("## Sonuç" + (" ve Öneriler" if doc_type == "thesis" else ""))
    lines.append("[YAZAR NOTU: Sonuç ve varsa öneriler burada yazılmalıdır.]")
    lines.append("")
    return "\n".join(lines)
