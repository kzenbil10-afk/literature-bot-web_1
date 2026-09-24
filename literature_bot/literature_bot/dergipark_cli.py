"""Standalone indexing tool for the DergiPark local cache.

DergiPark has no live keyword-search API (see sources/dergipark.py for why),
so before "dergipark" shows up as a source in a `literature_bot` search, its
local cache has to be built at least once with this tool:

    # 1) find the journals ("sets") relevant to your field
    python3 -m literature_bot.dergipark_cli list-sets --query "tıp"

    # 2) harvest their full text/metadata into the local cache
    python3 -m literature_bot.dergipark_cli index --sets 123,456,mulkiye

    # 3) now `--sources dergipark` (or "...,dergipark") works in a normal search
    python3 -m literature_bot.dergipark_cli stats
"""
from __future__ import annotations

import argparse
import sys

from . import dergipark_cache
from .sources import dergipark


def cmd_list_sets(args: argparse.Namespace) -> int:
    print("DergiPark'taki dergi listesi çekiliyor (bir kereye mahsus, biraz sürebilir)...", file=sys.stderr)
    sets = dergipark.fetch_sets()
    if args.query:
        q = args.query.lower()
        sets = [s for s in sets if q in s["set_name"].lower()]
    print(f"{len(sets)} dergi bulundu.\n")
    for s in sets[: args.limit]:
        print(f"{s['set_spec']}\t{s['set_name']}")
    if len(sets) > args.limit:
        print(f"\n... ve {len(sets) - args.limit} tane daha (--limit ile artırabilirsiniz)")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    set_specs = [s.strip() for s in args.sets.split(",") if s.strip()] if args.sets else [None]
    if set_specs == [None] and not args.all:
        print(
            "Hangi dergileri indeksleyeceğinizi --sets ile belirtin (virgülle ayrılmış setSpec listesi; "
            "önce 'list-sets' ile bulun), ya da TÜM DergiPark'ı indekslemek için --all kullanın "
            "(çok uzun sürebilir ve büyük bir yerel veritabanı oluşturur).",
            file=sys.stderr,
        )
        return 2

    con = dergipark_cache.connect(args.db)
    total_written = 0
    for set_spec in set_specs:
        label = set_spec or "(tüm DergiPark)"
        print(f"[{label}] taranıyor...", file=sys.stderr)
        set_total = 0
        for batch in dergipark.harvest_records(
            set_spec=set_spec,
            since=args.since,
            until=args.until,
            max_records=args.max_records,
        ):
            written = dergipark_cache.upsert_records(con, batch)
            set_total += written
            total_written += written
            print(f"  ... {set_total} kayıt işlendi", file=sys.stderr)
        if set_spec:
            dergipark_cache.mark_harvested(con, set_spec, set_total)
        print(f"[{label}] tamamlandı: {set_total} kayıt.", file=sys.stderr)

    print(f"\nToplam {total_written} kayıt '{args.db}' içine yazıldı.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    con = dergipark_cache.connect(args.db)
    s = dergipark_cache.stats(con)
    print(f"Veritabanı: {args.db}")
    print(f"Toplam kayıt: {s['total_records']}")
    print(f"İndekslenen dergi sayısı: {s['indexed_journals']}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="literature_bot.dergipark_cli", description=__doc__)
    p.add_argument("--db", default=dergipark_cache.DEFAULT_DB_PATH, help="Yerel önbellek veritabanı yolu")
    sub = p.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-sets", help="DergiPark'taki dergileri listele (yerel filtre ile)")
    p_list.add_argument("--query", default=None, help="Dergi adında aranacak anahtar kelime, örn. 'tıp'")
    p_list.add_argument("--limit", type=int, default=100)
    p_list.set_defaults(func=cmd_list_sets)

    p_index = sub.add_parser("index", help="Seçilen dergileri OAI-PMH ile yerel önbelleğe indir")
    p_index.add_argument("--sets", default=None, help="Virgülle ayrılmış setSpec listesi (list-sets çıktısından)")
    p_index.add_argument("--all", action="store_true", help="TÜM DergiPark'ı indeksle (çok büyük/uzun)")
    p_index.add_argument("--since", default=None, help="YYYY-MM-DD -- bu tarihten sonraki kayıtlar")
    p_index.add_argument("--until", default=None, help="YYYY-MM-DD -- bu tarihe kadarki kayıtlar")
    p_index.add_argument("--max-records", type=int, default=None, help="Dergi başına maksimum kayıt (test için)")
    p_index.set_defaults(func=cmd_index)

    p_stats = sub.add_parser("stats", help="Yerel önbellekteki kayıt/dergi sayısını göster")
    p_stats.set_defaults(func=cmd_stats)

    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
