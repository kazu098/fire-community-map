#!/usr/bin/env python3
"""指定したメンバーでマッチングしたと仮定して、ゆるマッチングの案内文を表示するだけのプレビュー。

Supabaseを読むだけで、書き込み・Discord投稿はしない(メンションも付けない)。
例: python3 scripts/preview_yuru_announcement.py かず みかん さとりーまん ドロリッチ
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import process_member_match_schedules as schedules
import run_member_matching as matching
from yuru_talk_group_topics import build_group_topics, format_topic_line


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview the ゆるマッチング announcement for the given members.")
    parser.add_argument("nicknames", nargs="+", help="3〜4人のニックネーム(サイトの表記どおり)")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--seed", type=int, default=None, help="ランダムに選ぶ問いかけを固定する")
    args = parser.parse_args()

    matching.load_dotenv(Path(args.env_file))
    supabase_url = matching.require_env("SUPABASE_URL")
    key = matching.require_env("SUPABASE_SERVICE_ROLE_KEY")

    def get(path: str) -> Any:
        req = Request(f"{supabase_url}{path}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    names_filter = quote(f"({','.join(json.dumps(n, ensure_ascii=False) for n in args.nicknames)})")
    tags: dict[str, dict[str, list[str]]] = {}
    for row in get(f"/rest/v1/member_tags?select=member_nickname,category,value&member_nickname=in.{names_filter}"):
        tags.setdefault(row["member_nickname"], {}).setdefault(row["category"], []).append(row["value"])
    profiles = {
        p["nickname"]: p for p in get(f"/rest/v1/member_profiles?select=nickname,self_intro_text&nickname=in.{names_filter}")
    }
    signals = {
        s["member_nickname"]: s
        for s in get(
            f"/rest/v1/member_interest_signals?select=member_nickname,recent_themes,theme_counts"
            f"&member_nickname=in.{names_filter}"
        )
    }
    missing = [n for n in args.nicknames if n not in profiles]
    if missing:
        raise SystemExit(f"見つからないニックネーム: {', '.join(missing)}")

    members = [
        {
            "nickname": n,
            "tags": tags.get(n, {}),
            "intro": profiles[n].get("self_intro_text"),
            "recent_themes": (signals.get(n) or {}).get("recent_themes") or [],
        }
        for n in args.nicknames
    ]
    print("最近の投稿から判定したテーマ:")
    for m in members:
        print(f"  {m['nickname']}: {', '.join(m['recent_themes']) or '(なし)'}")

    topics = build_group_topics(members, random.Random(args.seed))
    print("\n話題の出どころ:")
    for t in topics:
        print(f"  [{t['source']}] {format_topic_line(t, args.nicknames)}")

    match = {"members": args.nicknames, "day_of_week": "sat", "hour": 10}
    url = f"{matching.SITE_BASE_URL}/?view=yuru-talk&group=<group_id>"
    print("\n===== マッチング告知 =====")
    print(matching.format_announcement(match, topics, {}, yuru_talk_url=url))
    print("\n===== 通話部屋のチャット =====")
    print(schedules.format_voice_channel_topics(topics, args.nicknames, "<group_id>"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
