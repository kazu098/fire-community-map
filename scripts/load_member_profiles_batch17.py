#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the seventeenth tag-display batch.

Batch 17 adds 2 members: 推し旅トラベラー and ヒライム.

推し旅トラベラー's form nickname differs from the Discord display name
(`推し旅トラベラー０`); config/member_discord_name_map.csv already covers that
mapping. ヒライム had no formal self-introduction post in the self-intro channel
at the time of this import, so the profile is seeded with avatar data only and
empty tags.

Same upsert pattern as load_member_profiles.py / batch2-16.
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


PROFILES = [
    {
        "nickname": "推し旅トラベラー",
        "avatar_url": "https://cdn.discordapp.com/avatars/1392505219761438811/3a66cfb9b44a4684f126ee7c18d1dd6e.png?size=128",
        "self_intro_text": (
            "はじめまして、推し旅トラベラーです。\n"
            "どうぞよろしくお願いいたします。\n"
            "\n"
            "【ニックネーム】\n"
            "　→  推し旅トラベラー (noteでのハンドル)\n"
            "【属性】\n"
            "　→  定年を過ぎてシニア継続雇用の会社員\n"
            "【年齢・居住地（ざっくりでOK）】\n"
            "　→ 60代前半／湘南在住\n"
            "【現在の仕事・収入源】\n"
            "　→  フルタイムの会社員(シニアになって、収入は1/2以下に)\n"
            "　　パートナーもフルタイムの会社員。今や私より収入は多い。\n"
            "【投資・資産運用の状況】\n"
            "　→ 投資信託メイン。\n"
            "　　旅関係など応援と配当・株主優待が両立できる企業の株を10社ほど\n"
            "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】\n"
            "　→ 国内とアジアをぶらぶらと旅したい\n"
            "【一言】\n"
            "　→ シニア継続雇用は収入の面ではメリットあるけれど、やりがい的にはビミョウ。\n"
            "　　NPO関連の活動など、これまでとは違う生き方を模索中。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1392509981546516663",
        "self_intro_posted_at": "2025-07-09T14:17:31.185000+00:00",
    },
    {
        "nickname": "ヒライム",
        "avatar_url": "https://cdn.discordapp.com/avatars/903652538832805898/bbea6797c5be10b64690a5ba55f33147.png?size=128",
        "self_intro_text": None,
        "self_intro_url": None,
        "self_intro_posted_at": None,
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "推し旅トラベラー": [],
    "ヒライム": [],
}

# category is one of: investment_style, fire_status, mbti, skill, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "推し旅トラベラー": {
        "investment_style": ["投資信託", "個別株", "配当・株主優待"],
        "fire_status": ["シニア継続雇用"],
        "mbti": [],
        "skill": [],
        "interest": ["国内旅行", "アジア旅行", "NPO活動"],
    },
    "ヒライム": {
        "investment_style": [],
        "fire_status": [],
        "mbti": [],
        "skill": [],
        "interest": [],
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
    parser = argparse.ArgumentParser(description="Seed batch 17 of member_profiles/member_tags/member_links.")
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
        for link in MEMBER_LINKS.get(nickname, []):
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

    if tag_rows:
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
