#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirtieth tag-display batch (1 member: matcha).

The tag-display form response only contained the opt-in nickname. Profile
content below is curated from the member's Discord self-introduction post
(posted 2026-04-11, well before the 2026-09-04 tag-display form opt-in).
Same upsert pattern as load_member_profiles.py / batch2-29.
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


SELF_INTRO_TEXT = (
    "はじめまして、matchaです。\n"
    "まさか当選できるとは、、本当に嬉しいです、ありがとうございます！！\n"
    "\n"
    "【ニックネーム】\n"
    "matcha\n"
    "\n"
    "【属性】\n"
    "まだサラリーマンで仕事をしています。上司がアレなんで仕事を辞めたいなと思っていたタイミングでこちらのコミュニティを見つけて、「FIRE？わたしもできるかもしれない？？」と色々考え始めたところです。\n"
    "小学生の母です。\n"
    "\n"
    "【年齢、居住地】\n"
    "40代　東京\n"
    "\n"
    "【投資　資産運用の状況】\n"
    "ニーサ、DC（インデックス投資）、保険\n"
    "\n"
    "【無職になったらやりたいこと】\n"
    "ひたすらのんびりしたいです\n"
    "フラダンス\n"
    "水泳（体力をつけたい！）\n"
    "ヨガ\n"
    "\n"
    "【一言】\n"
    "うちはまだ持ち家がないので、完全に仕事を辞めることもできず、可能な限り働こうかなと思ってます。（みかんさんの言葉をお借りすると、魂が汚れる感じでして。）\n"
    "残りの人生の自由な時間を考えると悩ましくもあり、、\n"
    "そんな中でもFIRE研究所さんのnoteの記事を読んでると楽しくて、FIREどうこうより、みなさんと交流できることが楽しみになり、なんだかよく分からないけどワクワクしている感じです♪\n"
    "グチを言ったりしないみんながみんなのためにってどんな世界だろう？と、とても楽しみです！\n"
    "\n"
    "【キングダム診断】\n"
    "尾平（びへい）でした。\n"
    "当たってるようなやや違うような😅\n"
    "https://www.kingdomran.jp/shindan/bihei.html"
)


PROFILE = {
    "nickname": "matcha",
    "self_intro_text": SELF_INTRO_TEXT,
    "external_self_intro_text": SELF_INTRO_TEXT,
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1492511366953828372",
    "self_intro_posted_at": "2026-04-11T13:07:19.402000+00:00",
    "location_text": "東京",
    "nickname_public": False,
    "avatar_public": False,
    "self_intro_public": False,
    "location_public": False,
    "links_public": False,
}


# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "matcha": {
        "investment_style": ["NISA", "企業型DC", "インデックス投資"],
        "fire_status": ["会社員", "FIRE検討中"],
        "interest": ["フラダンス", "水泳", "ヨガ"],
    },
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {}


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
    parser = argparse.ArgumentParser(description="Seed batch 30 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    profiles = [PROFILE]
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
