"""Assembles the final Markdown report (+ separate .bib file) from search results."""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional

from .citations import bibliography_bibtex, format_apa
from .models import Paper
from .synthesis import build_theme_clusters, extractive_summary


def build_report(
    query: str,
    papers: List[Paper],
    sources_queried: List[str],
    raw_count: int,
    deep_synthesis: Optional[str] = None,
    n_themes: int = 5,
    translation_status: Optional[dict] = None,
    preview_status: Optional[dict] = None,
) -> str:
    today = datetime.date.today().isoformat()
    lines = []
    lines.append(f"# Literatür Taraması: {query}")
    lines.append("")
    lines.append(f"*Oluşturulma tarihi: {today}*")
    lines.append("")
    lines.append("## Yöntem")
    lines.append("")
    lines.append(f"- Taranan kaynaklar: {', '.join(sources_queried)}")
    lines.append(f"- Ham sonuç sayısı (tekilleştirme öncesi): {raw_count}")
    lines.append(f"- Tekilleştirme sonrası benzersiz kaynak sayısı: {len(papers)}")
    lines.append(
        "- Sıralama: sorgu terimi eşleşmesi, atıf sayısı ve güncellik ağırlıklandırılarak "
        "hesaplanan skora göre."
    )
    if translation_status:
        ts = translation_status
        if ts.get("engine_used"):
            lines.append(
                f"- Otomatik çeviri: {ts['total_considered']} yabancı-dil kaynaktan "
                f"{ts['translated']} tanesi '{ts['engine_used']}' motoruyla Türkçeye çevrildi "
                f"({ts['skipped_already_tr']} kaynak zaten Türkçe olduğu için atlandı"
                + (f", {ts['failed']} kaynak çevrilemedi" if ts.get("failed") else "")
                + ")."
            )
        elif ts.get("total_considered"):
            lines.append(
                f"- Otomatik çeviri denendi ancak başarısız oldu ({ts['total_considered']} kaynak için); "
                "orijinal (İngilizce/diğer dil) başlık ve özetler gösteriliyor."
            )
    if preview_status:
        ps = preview_status
        lines.append(
            f"- Tam metin önizlemesi: {ps['attempted']} kaynak denendi, {ps['available']} tanesi için "
            "önizleme çıkarılabildi (hiçbiri kalıcı kaydedilmedi -- kaydetmek için `save --download` kullanın)."
        )
    lines.append(
        "- Her kaynağın başındaki **#numara**, `python -m literature_bot save <numara>` komutuyla o "
        "kaynağı kütüphanenize kaydetmek için kullanılır."
    )
    lines.append("")

    lines.append("## Sentez")
    lines.append("")
    if deep_synthesis:
        lines.append(deep_synthesis.strip())
        lines.append("")
        lines.append(
            "_(Bu sentez, toplanan kaynakların özetleri temel alınarak Claude tarafından "
            "üretilmiştir. Atıfları ve iddiaları orijinal kaynaklarla karşılaştırarak doğrulayın.)_"
        )
    else:
        lines.append(
            "_LLM tabanlı derin sentez üretilemedi (ne ANTHROPIC_API_KEY ne de NVIDIA_API_KEY "
            "tanımlı, ya da API çağrısı başarısız oldu); aşağıda en alakalı kaynaklardan "
            "çıkarımsal (extractive) bir özet listelendi:_"
        )
        lines.append("")
        lines.append(extractive_summary(papers))
    lines.append("")

    lines.append("## Tematik Gruplandırma")
    lines.append("")
    clusters: Dict[str, List[Paper]] = build_theme_clusters(papers, n_themes=n_themes)
    for theme, theme_papers in clusters.items():
        lines.append(f"### {theme.capitalize()} ({len(theme_papers)} kaynak)")
        lines.append("")
        for p in theme_papers:
            tr_note = f" — *TR: {p.title_tr}*" if p.title_tr else ""
            lines.append(f"- {format_apa(p)}{tr_note}")
        lines.append("")

    if preview_status:
        lines.append("## Tam Metin Önizlemesi")
        lines.append("")
        lines.append(
            "_Bu önizlemeler PDF geçici olarak indirilip metni çıkarıldıktan sonra silinerek üretildi -- "
            "hiçbiri diskinizde kalıcı olarak durmuyor. Bir kaynağı gerçekten indirip saklamak isterseniz "
            "`save <numara> --download` kullanın._"
        )
        lines.append("")
        for i, p in enumerate(papers, 1):
            if p.preview_available is None:
                continue
            if p.preview_available:
                garbled_note = " — ⚠️ metin bozuk çıkmış olabilir" if p.preview_reason else ""
                lines.append(f"**#{i} — {p.first_author_surname()} ({p.year or 't.y.'})**{garbled_note}")
                lines.append(f"> {p.preview_text}")
            else:
                lines.append(f"**#{i} — {p.first_author_surname()} ({p.year or 't.y.'})** — önizleme yok ({p.preview_reason})")
            lines.append("")

    lines.append(
        "## Tam Kaynakça (APA)\n\n"
        "_Başlıklar atıf bütünlüğü için orijinal dilinde bırakılmıştır; Türkçe çeviriler yalnızca "
        "okuma kolaylığı içindir ve kaynak gösterirken kullanılmamalıdır._"
    )
    lines.append("")
    for i, p in enumerate(papers, 1):
        extra_bits = []
        if p.citation_count is not None:
            extra_bits.append(f"atıf: {p.citation_count}")
        if p.sources:
            extra_bits.append("kaynak: " + "/".join(p.sources))
        extra = f"  _({'; '.join(extra_bits)})_" if extra_bits else ""
        lines.append(f"**#{i}**. {format_apa(p)}{extra}")
        if p.title_tr:
            lines.append(f"   **TR başlık:** {p.title_tr}")
        if p.abstract:
            snippet = p.abstract[:300] + ("…" if len(p.abstract) > 300 else "")
            label = "> **(Orijinal)**" if p.abstract_tr else ">"
            lines.append(f"   {label} {snippet}")
        if p.abstract_tr:
            tr_snippet = p.abstract_tr[:300] + ("…" if len(p.abstract_tr) > 300 else "")
            lines.append(f"   > **(TR)** {tr_snippet}")
        lines.append("")

    return "\n".join(lines)


def build_bibtex(papers: List[Paper]) -> str:
    return bibliography_bibtex(papers)
