#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-eighth tag-display batch
(1 member: かつらぎ).

かつらぎ posted a Discord self-intro on 2026-10-09 (nickname declared as ひらがな "かつらぎ").
discord_user_id is set so the first Discord login links to this profile.
あた (already registered via Discord login) only needed self_intro_text backfilled; that was
patched directly and is not part of this script.

Same upsert pattern as load_member_profiles.py / batch2-37.
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
        "nickname": "かつらぎ",
        "discord_user_id": "1558023041953300510",
        "avatar_url": "https://cdn.discordapp.com/avatars/1558023041953300510/5445ffd7ffb201a98393cbdf684ea4b1.png?size=256",
        "location_text": "首都圏",
        "self_intro_text": "はじめまして！参加させていただけて嬉しいです😄 \n\n【ニックネーム】\nかつらぎ\n\n【属性】\n未FIRE\n既婚、未就学児1人\n\n【年齢・居住地】\nアラフォー、首都圏\n\n【収入源】\n給与所得\n\n【投資・資産運用の状況】\n以前は米国高配当も買っていましたが、現在はもっぱらオルカン積み上げ中です。\n\n【趣味、最近ハマってること】\n趣味でバンドのボーカルを細々やっております。漫画･アニメは昔から好きです。(子育て中の為スローペース)\n\n【無職になったらやりたいこと】\n世界一周！\nダイエット！笑\n\n【一言】\n会社員から一念発起し医師となりました。\n仕事と育児が両立できるようなバランスを探りながら日々生活する中で、FIRE済みおよびFIREを目指す方々のいらっしゃるこちらのコミュニティを見つけました。\n仕事がまだ半人前＋第2子も欲しいなと思っているので自身のFIREはもう少し先になりそうですが、皆さんの考え方やライフスタイルに触れながら自分なりの働き方やFIREの形を模索していけたらと思っています。\n\nどうぞよろしくお願いいたします！✨",
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1558112187199787198",
        "self_intro_posted_at": "2026-10-09T13:41:33.753000+00:00",
        "joined_month": "2026-10-01",
        "joined_month_source": "self_intro"
    }
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {}

MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "かつらぎ": {
        "fire_status": [
            "FIRE準備中"
        ],
        "investment_style": [
            "オルカン",
            "米国高配当株"
        ],
        "skill": [
            "医師"
        ],
        "interest": [
            "バンド",
            "ボーカル",
            "漫画",
            "アニメ"
        ],
        "wants_to_know": [
            "FIRE後の働き方"
        ]
    }
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
    parser = argparse.ArgumentParser(description="Seed batch 38 of member_profiles/member_tags/member_links.")
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
