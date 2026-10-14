#!/usr/bin/env python3
"""開催が決まっていて、まだ開催前のゆるマッチングの通話部屋に「この人に聞いてみたい」とネタを投稿する(一回限りの補完用)。

2026-10-14に話題の作り方を変えた(PR #383)時点で、開催決定済み・通話部屋作成済みの組には
新しい話題が届かない(通話部屋への投稿は開催決定のときだけ行うため)。その組の分を、
マッチング時と同じロジックで作ってmember_match_group_topicsに保存し、通話部屋のチャットに投稿する。

ランダムに選ぶ部分(テーマの問いかけ・聞いてみたいの一言)はgroup_idで乱数を固定しているので、
--dry-runで確認した文面と同じものが投稿される。既に話題が保存済みの組はスキップする(二重投稿防止)。
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import process_member_match_schedules as schedules
import run_member_matching as matching
from yuru_talk_group_topics import build_group_topics


def main() -> int:
    parser = argparse.ArgumentParser(description="Post new-style topics to upcoming ゆるマッチング voice channels (one-off).")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="Print the messages without saving or posting.")
    parser.add_argument("--markdown", help="With --dry-run, also write the messages to this .md file.")
    args = parser.parse_args()

    matching.load_dotenv(Path(args.env_file))
    supabase_url = matching.require_env("SUPABASE_URL")
    key = matching.require_env("SUPABASE_SERVICE_ROLE_KEY")
    bot_token = None if args.dry_run else matching.require_env("DISCORD_BOT_TOKEN")

    def get(path: str) -> Any:
        req = Request(f"{supabase_url}{path}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    now = datetime.now(timezone.utc)
    upcoming = get(
        "/rest/v1/member_match_schedules?select=group_id,confirmed_date,voice_channel_id"
        "&status=eq.confirmed&voice_channel_id=not.is.null&voice_channel_deleted_at=is.null"
        f"&confirmed_date=gt.{quote(now.isoformat())}&order=confirmed_date.asc"
    )
    tags: dict[str, dict[str, list[str]]] = {}
    for row in get("/rest/v1/member_tags?select=member_nickname,category,value"):
        tags.setdefault(row["member_nickname"], {}).setdefault(row["category"], []).append(row["value"])
    profiles = {p["nickname"]: p for p in get("/rest/v1/member_profiles?select=nickname,self_intro_text")}
    signals = {s["member_nickname"]: s for s in get("/rest/v1/member_interest_signals?select=member_nickname,recent_themes")}
    hooks_by_nickname = {
        h["member_nickname"]: h.get("hooks") or []
        for h in get("/rest/v1/member_conversation_hooks?select=member_nickname,hooks")
    }

    md_lines = ["# 開催前のゆるマッチング: 通話部屋に投稿する文面", "", f"{now.astimezone(matching.JST):%Y-%m-%d %H:%M} 時点で開催決定済み・開催前の組。", ""]
    for schedule in upcoming:
        group_id = schedule["group_id"]
        existing = get(f"/rest/v1/member_match_group_topics?group_id=eq.{group_id}&select=group_topics,member_hooks")
        if existing and (existing[0].get("group_topics") or existing[0].get("member_hooks")):
            print(f"skip {group_id}: topics already saved")
            continue
        nicknames = [
            r["member_nickname"] for r in get(f"/rest/v1/member_match_group_members?group_id=eq.{group_id}&select=member_nickname")
        ]
        members = [
            {
                "nickname": n,
                "tags": tags.get(n, {}),
                "intro": (profiles.get(n) or {}).get("self_intro_text"),
                "recent_themes": (signals.get(n) or {}).get("recent_themes") or [],
            }
            for n in nicknames
        ]
        rng = random.Random(group_id)
        group_topics = build_group_topics(members, rng)
        member_hooks = matching.pick_member_hooks(nicknames, hooks_by_nickname, rng)
        content = schedules.format_voice_channel_topics(group_topics, nicknames, group_id, member_hooks)

        when = datetime.fromisoformat(schedule["confirmed_date"]).astimezone(matching.JST)
        title = f"{when.month}/{when.day}({matching.WEEKDAY_KANJI[when.weekday()]}) {when:%H:%M}〜 {' / '.join(nicknames)}"
        print(f"\n===== {title}\n{content}")
        md_lines += [f"## {title}", "", "```", content, "```", ""]
        if args.dry_run:
            continue

        # 投稿してから保存する(保存だけ済んで投稿に失敗すると、次回の実行でスキップされて届かなくなるため)。
        # 古い作りの通話部屋でBotの書き込みが拒否されるなど、1組の失敗で残りを止めない。
        try:
            matching.discord_post(schedule["voice_channel_id"], bot_token, content)
        except RuntimeError as exc:
            print(f"post failed for {group_id}, not saved (retry later): {exc}")
            continue
        if existing:
            matching.supabase_request(
                "PATCH", f"{supabase_url}/rest/v1/member_match_group_topics?group_id=eq.{group_id}", key,
                body={"group_topics": group_topics, "member_hooks": member_hooks}, prefer="return=minimal",
            )
        else:
            matching.supabase_request(
                "POST", f"{supabase_url}/rest/v1/member_match_group_topics", key,
                body=[{"group_id": group_id, "group_topics": group_topics, "member_hooks": member_hooks}],
                prefer="return=minimal",
            )
        print(f"posted to voice channel {schedule['voice_channel_id']} and saved")

    if args.dry_run and args.markdown:
        Path(args.markdown).write_text("\n".join(md_lines), encoding="utf-8")
        print(f"\nwrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
