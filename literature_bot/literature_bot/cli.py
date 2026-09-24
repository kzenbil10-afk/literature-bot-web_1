"""Command-line entry point, with subcommands:

    search   Tara, sırala, (isteğe bağlı) önizle -- hiçbir şeyi kalıcı kaydetmez.
    save     Son aramadan seçtiğiniz kaynak(lar)ı kütüphaneye kaydeder;
             --download verilirse SADECE o kaynak(lar) için gerçek PDF indirir.
    library  Kütüphanenizdeki kayıtlı kaynakları listeler.
    remove   Kütüphaneden bir kaydı siler.
    draft    Kütüphanenizdeki (bir koleksiyondaki) kaynaklardan sentezlenmiş
             bir makale/tez taslağı üretir.

Tipik akış:

    python -m literature_bot search "eğitimde yapay zeka" --sources dergipark,crossref --preview-fulltext
    python -m literature_bot save 1,3,5 --collection tez-bolum2 --download
    python -m literature_bot library --collection tez-bolum2
    python -m literature_bot draft --collection tez-bolum2 --type thesis --output taslak.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import dergipark_cache, library, llm_client, session_cache
from .citations import bibliography_bibtex, format_apa
from .fulltext import fetch_fulltexts, preview_fulltexts, save_one_fulltext
from .ranking import sort_papers
from .report import build_report
from .search import run_search
from .sources import ALL_SOURCES
from .synthesis import deep_research_synthesis, generate_draft, template_draft
from .translation import translate_papers


# ============================================================================
# shared LLM provider args (search --deep-research, translate, draft)
# ============================================================================

def _add_llm_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--provider", choices=["auto", "anthropic", "nvidia"], default="auto",
        help="Kullanılacak LLM sağlayıcısı. auto: ANTHROPIC_API_KEY tanımlıysa Claude, yoksa "
        "NVIDIA_API_KEY tanımlıysa NVIDIA NIM kullanılır (varsayılan: auto)",
    )
    p.add_argument(
        "--model", default=None,
        help="Kullanılacak model adı (verilmezse sağlayıcıya göre makul bir varsayılan "
        "seçilir -- Claude için 'claude-sonnet-4-5', NVIDIA için 'mistralai/mistral-nemotron'; "
        "LLM_MODEL ortam değişkeniyle de ayarlanabilir)",
    )


# ============================================================================
# search
# ============================================================================

def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("query", help="Araştırma konusu / arama sorgusu")
    p.add_argument(
        "--sources",
        default=",".join(ALL_SOURCES),
        help=f"Virgülle ayrılmış kaynak listesi. Seçenekler: {', '.join(ALL_SOURCES)} (varsayılan: hepsi)",
    )
    p.add_argument("--limit-per-source", type=int, default=20, help="Her kaynaktan çekilecek maksimum kayıt sayısı")
    p.add_argument("--max-results", type=int, default=40, help="Raporda yer alacak toplam (tekilleştirilmiş) kaynak sayısı")
    p.add_argument("--year-min", type=int, default=None, help="En eski yayın yılı filtresi")
    p.add_argument("--year-max", type=int, default=None, help="En yeni yayın yılı filtresi")
    p.add_argument("--sort", choices=["relevance", "citations", "year"], default="relevance")
    p.add_argument("--output", default="literatur_raporu.md", help="Markdown rapor dosya yolu")
    p.add_argument("--bibtex", default="kaynaklar.bib", help="BibTeX çıktı dosya yolu")
    p.add_argument("--json", default=None, help="(opsiyonel) ham sonuçları JSON olarak da kaydet")
    p.add_argument(
        "--deep-research", action="store_true",
        help="Bir LLM sağlayıcısı (Claude ya da NVIDIA) yapılandırılmışsa gerçek bir genel sentez üret",
    )
    _add_llm_args(p)
    p.add_argument("--language", choices=["tr", "en"], default="tr", help="Sentez çıktı dili")
    p.add_argument("--openalex-email", default=os.environ.get("OPENALEX_EMAIL"), help="OpenAlex 'polite pool' için e-posta (isteğe bağlı)")
    p.add_argument("--s2-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY"), help="Semantic Scholar API anahtarı (isteğe bağlı)")
    p.add_argument("--pubmed-key", default=os.environ.get("PUBMED_API_KEY"), help="NCBI API anahtarı (isteğe bağlı)")
    p.add_argument(
        "--dergipark-db",
        default=os.environ.get("DERGIPARK_DB", dergipark_cache.DEFAULT_DB_PATH),
        help="DergiPark yerel önbellek veritabanı yolu (önce 'python -m literature_bot.dergipark_cli index ...' ile oluşturulmalı)",
    )
    p.add_argument("--n-themes", type=int, default=5, help="Tematik gruplandırmada oluşturulacak başlık sayısı")
    p.add_argument(
        "--no-translate", dest="translate", action="store_false",
        help="Yabancı dildeki başlık/özetlerin otomatik Türkçe çevirisini kapat (varsayılan: açık)",
    )
    p.add_argument(
        "--translate-engine", choices=["auto", "claude", "nvidia", "mymemory", "google", "none"], default="auto",
        help="auto: bir LLM sağlayıcısı (Claude/NVIDIA) yapılandırılmışsa onu, yoksa ücretsiz bir "
        "motoru kullanır (varsayılan: auto)",
    )
    p.set_defaults(translate=True)
    p.add_argument(
        "--preview-fulltext", action="store_true",
        help="En alakalı sonuçlar için PDF'i geçici indirip kısa bir metin önizlemesi göster -- "
        "HİÇBİR ŞEY KALICI KAYDEDİLMEZ (kaydetmek için ayrıca 'save --download' kullanın)",
    )
    p.add_argument("--preview-limit", type=int, default=5, help="En fazla kaç sonuç için önizleme denensin")
    p.add_argument("--preview-chars", type=int, default=1200, help="Önizlemede gösterilecek maksimum karakter")
    p.add_argument("--unpaywall-email", default=os.environ.get("UNPAYWALL_EMAIL"), help="Unpaywall için iletişim e-postası (önizleme/indirme için önerilir)")
    p.add_argument("--ocr-max-pages", type=int, default=5, help="Önizlemede OCR gereken PDF'lerde işlenecek maksimum sayfa")
    p.add_argument("--session-file", default=session_cache.DEFAULT_SESSION_PATH, help="Sonuçların yazılacağı oturum dosyası (save komutu bunu okur)")
    p.add_argument("--quiet", action="store_true")


def cmd_search(args: argparse.Namespace) -> int:
    source_names = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in source_names if s not in ALL_SOURCES]
    if unknown:
        print(f"Bilinmeyen kaynak(lar): {unknown}. Geçerli seçenekler: {ALL_SOURCES}", file=sys.stderr)
        return 2

    if "dergipark" in source_names and not os.path.exists(args.dergipark_db):
        print(
            f"[uyarı] DergiPark seçildi ama '{args.dergipark_db}' bulunamadı; önce indekslemeniz gerekiyor:\n"
            f"        python -m literature_bot.dergipark_cli list-sets --query <alan-adı>\n"
            f"        python -m literature_bot.dergipark_cli index --sets <setSpec1,setSpec2,...>\n"
            f"        Bu çalıştırmada DergiPark sonuçsuz geçilecek.",
            file=sys.stderr,
        )

    if not args.quiet:
        print(f"[1/5] Sorgu: '{args.query}' | Kaynaklar: {source_names}")

    ranked, counts, raw_total = run_search(
        query=args.query,
        source_names=source_names,
        limit_per_source=args.limit_per_source,
        year_min=args.year_min,
        year_max=args.year_max,
        openalex_email=args.openalex_email,
        s2_api_key=args.s2_key,
        pubmed_api_key=args.pubmed_key,
        dergipark_db=args.dergipark_db,
    )
    if not args.quiet:
        print(f"[2/5] Kaynak başına sonuç: {counts} | Ham toplam: {raw_total} | Tekil: {len(ranked)}")

    ranked = sort_papers(ranked, by=args.sort)[: args.max_results]

    provider = None if args.provider == "auto" else args.provider
    if not args.quiet:
        detected = llm_client.detect_provider(provider)
        if detected:
            print(f"[bilgi] LLM sağlayıcısı: {detected} (model: {args.model or llm_client.default_model(detected)})")
        elif args.translate_engine in ("auto", "claude", "nvidia") or args.deep_research:
            print("[bilgi] Hiçbir LLM sağlayıcısı yapılandırılmadı (ANTHROPIC_API_KEY / NVIDIA_API_KEY yok) -> ücretsiz/kural tabanlı yollara düşülecek")

    translation_status = None
    if args.translate and args.translate_engine != "none":
        translation_status = translate_papers(
            ranked, engine=args.translate_engine, model=args.model, provider=provider,
        )
        if not args.quiet:
            print(f"[3/5] Çeviri -> {translation_status}")
    elif not args.quiet:
        print("[3/5] Otomatik çeviri kapalı")

    deep_synthesis = None
    if args.deep_research:
        deep_synthesis = deep_research_synthesis(
            query=args.query, papers=ranked, model=args.model, provider=provider, language=args.language,
        )
        if not args.quiet:
            print("[4/5] Derin sentez üretildi" if deep_synthesis else "[4/5] Derin sentez üretilemedi (anahtar yok/hata) -> çıkarımsal özet kullanılacak")
    elif not args.quiet:
        print("[4/5] Derin sentez atlandı (--deep-research verilmedi)")

    preview_status = None
    if args.preview_fulltext:
        if not args.quiet:
            print(f"[5/5] Tam metin önizlemesi hazırlanıyor (en fazla {args.preview_limit} kaynak, kalıcı kayıt YOK)...")
        preview_status = preview_fulltexts(
            ranked,
            max_count=args.preview_limit,
            unpaywall_email=args.unpaywall_email,
            preview_chars=args.preview_chars,
            ocr_max_pages=args.ocr_max_pages,
        )
        if not args.quiet:
            print(f"      -> {preview_status}")
    elif not args.quiet:
        print("[5/5] Tam metin önizleme atlandı (--preview-fulltext verilmedi)")

    report_md = build_report(
        query=args.query, papers=ranked, sources_queried=source_names, raw_count=raw_total,
        deep_synthesis=deep_synthesis, n_themes=args.n_themes,
        translation_status=translation_status, preview_status=preview_status,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report_md)

    with open(args.bibtex, "w", encoding="utf-8") as f:
        f.write(bibliography_bibtex(ranked))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "ref": i, "title": p.title, "authors": p.authors, "year": p.year, "venue": p.venue,
                        "doi": p.doi, "url": p.url, "pdf_url": p.pdf_url, "citation_count": p.citation_count,
                        "sources": p.sources, "score": p.score, "abstract": p.abstract,
                        "title_tr": p.title_tr, "abstract_tr": p.abstract_tr,
                        "preview_available": p.preview_available, "preview_text": p.preview_text,
                    }
                    for i, p in enumerate(ranked, 1)
                ],
                f, ensure_ascii=False, indent=2,
            )

    session_cache.write_last_search(args.query, ranked, path=args.session_file)

    if not args.quiet:
        print(f"\nTamamlandı -> {args.output} ({len(ranked)} kaynak), {args.bibtex}")
        print("\nKaydetmek istediğiniz kaynağın numarasını not edin, örn:")
        print("  python -m literature_bot save 1,3 --collection tez-bolum2 --download\n")
        print(f"{'#':>3}  {'Yazar (Yıl)':<28} Başlık")
        for i, p in enumerate(ranked, 1):
            author_year = f"{p.first_author_surname()} ({p.year or 't.y.'})"
            title_short = (p.title[:70] + "…") if len(p.title) > 70 else p.title
            print(f"{i:>3}  {author_year:<28} {title_short}")

    return 0


# ============================================================================
# save
# ============================================================================

def _add_save_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("refs", help="Son aramadan numara(lar), virgülle ayrılmış (örn: 1,3,7)")
    p.add_argument("--collection", default="genel", help="Kaydedilecek koleksiyon adı")
    p.add_argument(
        "--download", action="store_true",
        help="SADECE bu kaynak(lar) için gerçek PDF'i indir ve metnini çıkar (isteğe bağlı; varsayılan: kapalı, sadece bilgiler kaydedilir)",
    )
    p.add_argument("--session-file", default=session_cache.DEFAULT_SESSION_PATH, help="Okunacak oturum (son arama) dosyası")
    p.add_argument("--library-db", default=library.DEFAULT_DB_PATH)
    p.add_argument("--library-dir", default=library.DEFAULT_FILES_DIR, help="--download ile indirilen PDF/metin dosyalarının klasörü")
    p.add_argument("--unpaywall-email", default=os.environ.get("UNPAYWALL_EMAIL"))
    p.add_argument("--ocr-max-pages", type=int, default=15)


def cmd_save(args: argparse.Namespace) -> int:
    data = session_cache.read_last_search(args.session_file)
    if not data:
        print(
            f"'{args.session_file}' bulunamadı. Önce bir arama yapın, örn:\n"
            f"  python -m literature_bot search \"konunuz\"",
            file=sys.stderr,
        )
        return 2

    try:
        refs = [int(x.strip()) for x in args.refs.split(",") if x.strip()]
    except ValueError:
        print("refs virgülle ayrılmış sayı(lar) olmalı, örn: 1,3,7", file=sys.stderr)
        return 2

    papers_by_ref = {}
    for ref in refs:
        if 1 <= ref <= len(data["papers"]):
            papers_by_ref[ref] = data["papers"][ref - 1]
        else:
            print(f"[uyarı] #{ref} son aramada yok (1-{len(data['papers'])} arası olmalı), atlanıyor", file=sys.stderr)

    if not papers_by_ref:
        print("Kaydedilecek geçerli kaynak yok.", file=sys.stderr)
        return 2

    con = library.connect(args.library_db)
    for ref, paper in papers_by_ref.items():
        if args.download:
            print(f"  #{ref} için tam metin indiriliyor...")
            save_one_fulltext(
                paper, out_dir=args.library_dir, unpaywall_email=args.unpaywall_email,
                ocr_max_pages=args.ocr_max_pages,
            )
        saved_id = library.save_paper(con, paper, collection=args.collection)
        status_note = f" [tam metin: {paper.fulltext_status}]" if args.download else ""
        print(f"  kaydedildi -> id={saved_id} | {paper.first_author_surname()} ({paper.year or 't.y.'}) \"{paper.title[:60]}\" [{args.collection}]{status_note}")

    print(f"\n{len(papers_by_ref)} kaynak '{args.collection}' koleksiyonuna kaydedildi ({args.library_db}).")
    return 0


# ============================================================================
# library / remove
# ============================================================================

def _add_library_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--collection", default=None, help="Yalnızca bu koleksiyonu listele (varsayılan: hepsi)")
    p.add_argument("--library-db", default=library.DEFAULT_DB_PATH)


def cmd_library(args: argparse.Namespace) -> int:
    con = library.connect(args.library_db)
    entries = library.list_papers(con, collection=args.collection)
    if not entries:
        scope = f"'{args.collection}' koleksiyonunda" if args.collection else "kütüphanede"
        print(f"{scope} kayıtlı kaynak yok. 'save' komutuyla kaynak ekleyin.")
        return 0

    print(f"{'id':>4}  {'koleksiyon':<16} {'yazar (yıl)':<24} {'tam metin':<10} başlık")
    for e in entries:
        p = e["paper"]
        author_year = f"{p.first_author_surname()} ({p.year or 't.y.'})"
        has_ft = "evet" if p.fulltext_status == "ok" else ("pdf" if p.fulltext_status == "pdf_only" else "hayır")
        title_short = (p.title[:50] + "…") if len(p.title) > 50 else p.title
        print(f"{e['id']:>4}  {e['collection']:<16} {author_year:<24} {has_ft:<10} {title_short}")

    collections = library.list_collections(con)
    if not args.collection and len(collections) > 1:
        print(f"\nKoleksiyonlar: {', '.join(collections)}")
    return 0


def _add_remove_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("id", type=int, help="Kütüphaneden silinecek kaydın id'si ('library' komutuyla görebilirsiniz)")
    p.add_argument("--library-db", default=library.DEFAULT_DB_PATH)
    p.add_argument("--library-dir", default=library.DEFAULT_FILES_DIR)


def cmd_remove(args: argparse.Namespace) -> int:
    con = library.connect(args.library_db)
    ok = library.remove_paper(con, args.id, files_dir=args.library_dir)
    print(f"id={args.id} silindi." if ok else f"id={args.id} bulunamadı.")
    return 0 if ok else 1


# ============================================================================
# draft
# ============================================================================

def _add_draft_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--collection", default=None, help="Yalnızca bu koleksiyondaki kaynakları kullan (varsayılan: kütüphanedeki hepsi)")
    p.add_argument("--title", default=None, help="Taslağın başlığı (verilmezse koleksiyon adından türetilir)")
    p.add_argument("--type", dest="doc_type", choices=["article", "thesis"], default="article", help="makale mi tez bölümü mü")
    p.add_argument("--language", choices=["tr", "en"], default="tr")
    p.add_argument("--output", default="taslak.md")
    p.add_argument("--bibtex", default="taslak_kaynaklar.bib")
    _add_llm_args(p)
    p.add_argument("--library-db", default=library.DEFAULT_DB_PATH)
    p.add_argument("--max-source-chars", type=int, default=4000, help="Tam metni olan kaynaklarda kullanılacak maksimum karakter")


def cmd_draft(args: argparse.Namespace) -> int:
    con = library.connect(args.library_db)
    entries = library.list_papers(con, collection=args.collection)
    if not entries:
        scope = f"'{args.collection}' koleksiyonunda" if args.collection else "kütüphanede"
        print(f"{scope} kayıtlı kaynak yok. Önce 'save' ile kaynak kaydedin.", file=sys.stderr)
        return 2

    papers = [e["paper"] for e in entries]
    title = args.title or (f"{args.collection.capitalize()} Taslağı" if args.collection else "Literatür Taslağı")
    n_with_fulltext = sum(1 for p in papers if p.fulltext_status == "ok")

    provider = None if args.provider == "auto" else args.provider
    detected = llm_client.detect_provider(provider)
    if detected:
        print(f"[bilgi] LLM sağlayıcısı: {detected} (model: {args.model or llm_client.default_model(detected)})")

    print(f"{len(papers)} kaynaktan taslak üretiliyor ({n_with_fulltext} tanesi tam metinle)...")
    draft_text = generate_draft(
        title=title, papers=papers, doc_type=args.doc_type, language=args.language,
        model=args.model, provider=provider, max_source_chars=args.max_source_chars,
    )
    if draft_text is None:
        print("[uyarı] ne ANTHROPIC_API_KEY ne de NVIDIA_API_KEY tanımlı (ya da çağrı başarısız oldu); "
              "kural tabanlı bir iskelet taslak üretilecek (gerçek sentez değil).")
        draft_text = template_draft(title, papers, doc_type=args.doc_type)
    else:
        draft_text = f"# {title}\n\n{draft_text}"

    ordered = sorted(papers, key=lambda p: (p.first_author_surname().lower(), p.year or 0))
    bib_lines = ["## Kaynakça", ""]
    for p in ordered:
        bib_lines.append(f"- {format_apa(p)}")
    draft_text = draft_text.rstrip() + "\n\n" + "\n".join(bib_lines) + "\n"

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(draft_text)
    with open(args.bibtex, "w", encoding="utf-8") as f:
        f.write(bibliography_bibtex(ordered))

    print(f"\nTamamlandı -> {args.output} ({len(papers)} kaynak), {args.bibtex}")
    return 0


# ============================================================================
# entry point
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="literature-bot",
        description="Çok kaynaklı literatür taraması, kaynak bulma, kütüphane ve taslak yazım botu.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Tara, sırala, (isteğe bağlı) önizle -- kalıcı kayıt yapmaz")
    _add_search_args(p_search)
    p_search.set_defaults(func=cmd_search)

    p_save = sub.add_parser("save", help="Son aramadan seçilen kaynak(lar)ı kütüphaneye kaydet")
    _add_save_args(p_save)
    p_save.set_defaults(func=cmd_save)

    p_library = sub.add_parser("library", help="Kütüphanedeki kayıtlı kaynakları listele")
    _add_library_args(p_library)
    p_library.set_defaults(func=cmd_library)

    p_remove = sub.add_parser("remove", help="Kütüphaneden bir kaydı sil")
    _add_remove_args(p_remove)
    p_remove.set_defaults(func=cmd_remove)

    p_draft = sub.add_parser("draft", help="Kütüphanedeki kaynaklardan makale/tez taslağı üret")
    _add_draft_args(p_draft)
    p_draft.set_defaults(func=cmd_draft)

    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
