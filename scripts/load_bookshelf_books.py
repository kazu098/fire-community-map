#!/usr/bin/env python3
"""Seed public.bookshelf_books (本棚タブ).

source=fire_lab: FIRE研究所公式本(firekenkyujo.com/books/ より)。
source=member: メンバー著書。member_links に登録されたAmazonリンクのうち、
本人の著書と判断できるものを手作業で選定して転記している(自動抽出ではない)。

サムネイル画像はAmazon側のbot対策でスクレイピングできないため、
thumbnail_url は未設定のまま登録し、後日Supabase Storageにアップロードした
画像URLを個別に更新する運用とする。
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


FIRE_LAB_BOOKS: list[dict[str, Any]] = [
    {
        "title": "FIRE図鑑 第0巻",
        "author_name": "FIRE研究所ほか3名",
        "amazon_url": "https://www.amazon.co.jp/dp/B0H33SS9MK",
        "sort_order": 0,
    },
    {
        "title": "FIRE図鑑 第1巻",
        "author_name": "FIRE研究所ほか5名",
        "amazon_url": "https://amzn.to/4tdjPEL",
        "sort_order": 1,
    },
    {
        "title": "FIRE1年目の教科書",
        "author_name": "FIRE研究所ほか5名",
        "amazon_url": "https://www.amazon.co.jp/dp/B0HC5P552S",
        "sort_order": 2,
    },
    {
        "title": "FIREめし",
        "author_name": "FIRE研究所ほか4名",
        "amazon_url": "https://amzn.to/4nxvgWo",
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
        "sort_order": 0,
    },
    {
        "member_nickname": "みかん",
        "title": "FIRE？無職？1年生！",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B0eubD159",
        "sort_order": 1,
    },
    {
        "member_nickname": "みかん",
        "title": "パワハラ。休職。投資。そしてFIREへ",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B0iNEZL5w",
        "sort_order": 2,
    },
    {
        "member_nickname": "みかん",
        "title": "実はnoteで月3万円稼ぐのに1年かかりました",
        "author_name": "みかん",
        "amazon_url": "https://link.amazon/B00nK1wju",
        "sort_order": 3,
    },
    {
        "member_nickname": "ノコ",
        "title": "世界一周旅行の作り方",
        "author_name": "ノコ",
        "amazon_url": "https://amzn.to/3OAwtPQ",
        "sort_order": 4,
    },
    {
        "member_nickname": "ノコ",
        "title": "世界一周旅行の作り方〜旅のフォトブック",
        "author_name": "ノコ",
        "amazon_url": "https://amzn.to/48b96D2",
        "sort_order": 5,
    },
    {
        "member_nickname": "ノコ",
        "title": "ウズベキスタン旅行 フォトブック＆ガイド",
        "author_name": "ノコ",
        "amazon_url": "https://link.amazon/B0fcGS2TI",
        "sort_order": 6,
    },
    {
        "member_nickname": "第三環境",
        "title": "58歳サラリーマンがFIREするまでの100日",
        "author_name": "第三環境",
        "amazon_url": "https://amzn.asia/d/fXKiarz",
        "sort_order": 7,
    },
    {
        "member_nickname": "きらまりん",
        "title": None,  # タイトル未確認。label は「著書」のみだったため本人に確認要。
        "author_name": "きらまりん",
        "amazon_url": "https://amzn.to/3PXMNu8",
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
