#!/usr/bin/env python3
"""Seed public.bookshelf_books (本棚タブ).

source=fire_lab: FIRE研究所公式本(firekenkyujo.com/books/ より)。
source=member: メンバー著書。member_links に登録されたAmazonリンクのうち、
本人の著書と判断できるものを手作業で選定して転記している(自動抽出ではない)。

サムネイル画像はAmazon商品ページ自体は自動スクレイピングできない(bot対策)が、
Amazonの画像CDN(m.media-amazon.com)は直接取得できるため、ログイン済みブラウザで
各商品ページの表紙画像URLを確認したうえでダウンロードし、Supabase Storageの
bookshelf-coversバケットにアップロードした画像URLをthumbnail_urlに設定している。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


BOOKSHELF_COVERS_BASE = "https://hchlqnsretsbhumeojdk.supabase.co/storage/v1/object/public/bookshelf-covers"

FIRE_LAB_BOOKS: list[dict[str, Any]] = [
    {
        "title": "FIRE図鑑 第0巻",
        "author_name": "FIRE研究所ほか3名",
        "amazon_url": "https://www.amazon.co.jp/dp/B0H33SS9MK",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0H33SS9MK.jpg",
        "sort_order": 0,
    },
    {
        "title": "FIRE図鑑 第1巻",
        "author_name": "FIRE研究所ほか5名",
        "amazon_url": "https://amzn.to/4tdjPEL",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0GPGP298R.jpg",
        "sort_order": 1,
    },
    {
        "title": "FIRE1年目の教科書",
        "author_name": "FIRE研究所ほか5名",
        "amazon_url": "https://www.amazon.co.jp/dp/B0HC5P552S",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0HC5P552S.jpg",
        "sort_order": 2,
    },
    {
        "title": "FIREめし",
        "author_name": "FIRE研究所ほか4名",
        "amazon_url": "https://amzn.to/4nxvgWo",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0H1DGJM48.jpg",
        "sort_order": 3,
    },
]

# member_nickname は member_profiles.nickname と一致させる。
# title が None のものはラベルからタイトルを特定できなかったもの(要確認)。
MEMBER_BOOKS: list[dict[str, Any]] = [
    {
        "member_nickname": "みかん",
        "title": "100人のFIREコミュニティができるまで",
        "author_name": "FIREサラリーマン みかん",
        "amazon_url": "https://link.amazon/B0447PWrT",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0G1Z9XK1B.jpg",
        "sort_order": 0,
    },
    {
        "member_nickname": "みかん",
        "title": "FIRE？無職？1年生！",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B0eubD159",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0GTTPFZ5Z.jpg",
        "sort_order": 1,
    },
    {
        "member_nickname": "みかん",
        "title": "パワハラ。休職。投資。そしてFIREへ",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B0iNEZL5w",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0G4D385X3.jpg",
        "sort_order": 2,
    },
    {
        "member_nickname": "みかん",
        "title": "実はnoteで月3万円稼ぐのに1年かかりました",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B00nK1wju",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0FR22WB2D.jpg",
        "sort_order": 3,
    },
    {
        "member_nickname": "ノコ",
        "title": "世界一周旅行の作り方 - 旅の手配と準備 完全ガイド",
        "author_name": "ノコ",
        "amazon_url": "https://amzn.to/3OAwtPQ",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0GFCFVS7D.jpg",
        "sort_order": 4,
    },
    {
        "member_nickname": "ノコ",
        "title": "世界一周旅行の作り方 - 旅のフォトブック",
        "author_name": "ノコ",
        "amazon_url": "https://amzn.to/48b96D2",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0GQPX3GMV.jpg",
        "sort_order": 5,
    },
    {
        "member_nickname": "ノコ",
        "title": "ウズベキスタン旅行 フォトブック＆旅ガイド",
        "author_name": "ノコ",
        "amazon_url": "https://link.amazon/B0fcGS2TI",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0HCL8ZV5Y.jpg",
        "drive_pdf_url": "https://drive.google.com/file/d/1Sa5N0ihfQSo7av9BH6onH7TnvjOdJpHy/view",
        "sort_order": 6,
    },
    {
        "member_nickname": "第三環境",
        "title": "58歳サラリーマンがFIREするまでの100日",
        "author_name": "第三環境",
        "amazon_url": "https://amzn.asia/d/fXKiarz",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0FRZDJYT1.jpg",
        "sort_order": 7,
    },
    {
        "member_nickname": "きらまりん",
        "title": "絵でつづるぼくらのFIRE物語",
        "author_name": "きらまりん",
        "amazon_url": "https://amzn.to/3PXMNu8",
        "thumbnail_url": f"{BOOKSHELF_COVERS_BASE}/B0GMWXNTK6.jpg",
        "drive_pdf_url": "https://drive.google.com/file/d/1FhkcYosM3N7-hja53y1Cso2mkT6F4Esa/view",
        "sort_order": 8,
    },
]


def supabase_request(
    method: str,
    url: str,
    service_role_key: str,
    body: Any = None,
    prefer: str | None = None,
) -> Any:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase API error {exc.code} for {method} {url}: {error_body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase API request failed for {method} {url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed public.bookshelf_books.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    rows: list[dict[str, Any]] = []
    for book in FIRE_LAB_BOOKS:
        rows.append({
            "source": "fire_lab",
            "member_nickname": None,
            "title": book["title"],
            "author_name": book["author_name"],
            "amazon_url": book["amazon_url"],
            "thumbnail_url": book.get("thumbnail_url"),
            "drive_pdf_url": book.get("drive_pdf_url"),
            "sort_order": book["sort_order"],
        })
    skipped = [b for b in MEMBER_BOOKS if not b["title"]]
    for book in MEMBER_BOOKS:
        if not book["title"]:
            continue
        rows.append({
            "source": "member",
            "member_nickname": book["member_nickname"],
            "title": book["title"],
            "author_name": book["author_name"],
            "amazon_url": book["amazon_url"],
            "thumbnail_url": book.get("thumbnail_url"),
            "drive_pdf_url": book.get("drive_pdf_url"),
            "sort_order": book["sort_order"],
        })

    print(f"Prepared {len(rows)} books ({len(skipped)} skipped: title unknown).")
    for book in skipped:
        print(f"  skipped: {book['member_nickname']} / {book['amazon_url']} (title unknown)")

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/bookshelf_books?on_conflict=amazon_url",
        service_role_key,
        body=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted bookshelf_books.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
