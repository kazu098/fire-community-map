#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-seventh tag-display batch
(2 members: まさやん, りん).

まさやん has a Discord self-intro (posted 2025-09-07) plus master-spreadsheet details.
りん has no self-introduction post in the Discord channel yet (searched by display name and
by message content for "りん"/"【ニックネーム】\nりん" -- not found), so self_intro_text/
self_intro_url/self_intro_posted_at/avatar_url are left null; only the minimal tags available
from the master profile spreadsheet are seeded (かずさんの判断、2026-10-05).

Same upsert pattern as load_member_profiles.py / batch2-36.
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


PROFILES: list[dict[str, Any]] = [
    {
        "nickname": "まさやん",
        "avatar_url": "https://cdn.discordapp.com/avatars/720779993717801060/8bcab784330ab7004e0d7b070da58a9f.png?size=128",
        "location_text": "関東地方",
        "self_intro_text": (
            "【ニックネーム】\n"
            "まさやん\n"
            "\n"
            "【Xアカウント】\n"
            "@masayan_sun\n"
            "\n"
            "【属性】\n"
            "FIRA60目指している会社員・単身\n"
            "\n"
            "【年齢・居住地】\n"
            "50代後半/関東地方\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "シンクタンクで研究職・給与収入\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "現在はインデックス投資のみNISA枠埋め中です。特定口座でNISA前に購入した日本個別・ETF・投資信託を保有中。\n"
            "\n"
            "【無職になってやりたいこと】\n"
            "・海外旅行&全県巡り\n"
            "・仕事のためではなく自分のための学修・研究活動\n"
            "・新しい趣味の開拓\n"
            "\n"
            "【一言】\n"
            "2026年12月の早期退職を模索しています。リアルでは資産運用やFIREの話ってなかなかできないので、このコミュニティーで皆さんと楽しく交流できたら嬉しいです。よろしくお願いします！\n"
            "\n"
            "https://www.kingdomran.jp/shindan/ouhon.html"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1414170462014935051",
        "self_intro_posted_at": "2025-09-07T08:48:32.161Z",
    },
    {
        "nickname": "りん",
        "avatar_url": None,
        "location_text": "東京都",
        "self_intro_text": None,
        "self_intro_url": None,
        "self_intro_posted_at": None,
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "まさやん": [
        {"label": "note", "url": "https://note.com/masa_yan3"},
        {"label": "X", "url": "https://x.com/masayan_sun"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "まさやん": {
        "investment_style": ["オルカン", "S&P500", "日本個別株"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["INTP-T"],
        "skill": ["研究職"],
    },
    "りん": {
        "fire_status": ["サイドFIRE"],
        "investment_style": ["投資信託", "日本個別株"],
        "affiliation": ["個人事業"],
    },
}


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
    parser = argparse.ArgumentParser(description="Seed batch 37 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    profiles = PROFILES
    tag_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []

    for nickname, categories in MEMBER_TAGS.items():
        for category, values in categories.items():
            for i, value in enumerate(values):
                tag_rows.append(
                    {"member_nickname": nickname, "category": category, "value": value, "sort_order": i}
                )

    for nickname, links in MEMBER_LINKS.items():
        for link in links:
            link_rows.append(
                {"member_nickname": nickname, "label": link["label"], "url": link["url"]}
            )

    print(f"Prepared {len(profiles)} profiles, {len(tag_rows)} tags, {len(link_rows)} links.")

    if args.dry_run:
        print(json.dumps(
            {"profiles": profiles, "tags": tag_rows, "links": link_rows},
            ensure_ascii=False, indent=2,
        ))
        return 0

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/member_profiles?on_conflict=nickname",
        service_role_key,
        body=profiles,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted member_profiles.")

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/member_tags?on_conflict=member_nickname,category,value",
        service_role_key,
        body=tag_rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted member_tags.")

    if link_rows:
        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/member_links?on_conflict=member_nickname,url",
            service_role_key,
            body=link_rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print("Upserted member_links.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
