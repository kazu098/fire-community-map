#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-sixth tag-display batch
(1 member: しず).

Same upsert pattern as load_member_profiles.py / batch2-35.
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
        "nickname": "しず",
        "avatar_url": "https://cdn.discordapp.com/avatars/1425034209717784576/3e58f2c3460f3f4935ecf58f7b697bec.png?size=128",
        "location_text": "愛知県",
        "self_intro_text": (
            "みなさんはじめまして。しずと申します。これからよろしくお願いいたします！\n"
            "\n"
            "【ニックネーム】\n"
            "　しず\n"
            "\n"
            "【属性】\n"
            "夫と二人暮らし\n"
            "\n"
            "【年齢・居住地】\n"
            "30代後半・愛知\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "会社員共働き\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "NISAとiDeCo(インデックス投資)\n"
            "\n"
            "【経済的自立をしたらやりたいこと】\n"
            "→旅行に行ったり、読書や映画を見たり、自分の気の向くままにのんびり過ごしたいです。\n"
            "\n"
            "【一言】\n"
            "既にFIRE済みの方、FIREを目標に頑張っている方々と交流することで、多様な価値観に触れ合えたらと思っています。どうぞよろしくお願いいたします。\n"
            "\n"
            "https://www.kingdomran.jp/shindan/kyokai.html"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1425108520147353661",
        "self_intro_posted_at": "2025-10-07T13:12:28.439Z",
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "しず": [
        {"label": "note", "url": "https://note.com/shizu_lifeshift"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "しず": {
        "investment_style": ["インデックス投資（NISA・iDeCo）"],
        "fire_status": ["サイドFIRE目指し中"],
        "mbti": ["INFJ-T"],
        "interest": ["旅行", "読書", "映画鑑賞"],
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
    parser = argparse.ArgumentParser(description="Seed batch 36 of member_profiles/member_tags/member_links.")
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
