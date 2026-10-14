#!/usr/bin/env python3
"""メンバーの「最近の興味」を、Discordの投稿とnoteの記事から集めて保管する(ゆるマッチングの話題づくり用)。

LLM APIは使わない(従量課金を避ける、かずさんの判断)。マッチングのたびにクローリングすると
重いので、このスクリプトを1日1回まわしてmember_interest_signalsに結果を貯め、マッチング側
(run_member_matching.py → yuru_talk_group_topics.py)はそれを読むだけにする。

- Discord: 公開チャンネル(fetch_community_posts.pyと同じ一覧から「介護・医療」を除いたもの)の
  直近DISCORD_WINDOW_DAYS日の投稿。投稿者はmember_profiles.discord_user_idでメンバーに対応づけ、
  チャンネル自体のテーマ(CHANNEL_THEMES、例: 「旅行」チャンネル→travel)と本文のキーワード
  (yuru_talk_group_topics.themes_in_text)でテーマを数える。
- note: member_linksに登録されたnote.comのURLから公開RSS(https://note.com/<id>/rss)を読み、
  直近NOTE_WINDOW_DAYS日の記事のタイトル+抜粋のキーワードでテーマを数える。

保存するのはテーマ別の件数・しきい値を超えたテーマ・noteの記事タイトル(公開情報)だけで、
Discordの投稿本文は保存しない。テーブルはservice roleのみ読み書きできる(RLSでanonは不可)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from fetch_community_posts import (
    CHANNEL_CONTENT_TYPES,
    DIGEST_EXTRA_CHANNEL_NAMES,
    load_dotenv,
    require_env,
    snowflake_from_datetime,
)
from yuru_talk_group_topics import themes_in_text

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-interest-signals/0.1"
DISCORD_WINDOW_DAYS = 30
NOTE_WINDOW_DAYS = 60  # noteは投稿間隔が長めなのでDiscordより広めに見る
NOTE_MAX_TITLES = 5
# Discordは雑談のついでの一言でもキーワードに当たるので、2件以上でそのテーマに興味ありとみなす。
# noteは1記事でも書いていれば十分な興味のサイン。
DISCORD_MIN_COUNT = 2
NOTE_MIN_COUNT = 1
# キーワードは広めに拾うので、しきい値を超えたテーマが1人に6〜10個付いてしまう(2026-10の実データ)。
# 「いま特に関心があること」に絞るため、件数(noteは1記事=2件ぶん)の多い順に上位だけ残す。
MAX_RECENT_THEMES = 3
NOTE_WEIGHT = 2

# 病気・介護など踏み込んだ話題が中心のチャンネルは読まない。
EXCLUDED_CHANNELS = {"介護・医療"}
# チャンネル名そのものがテーマを表しているもの。そのチャンネルへの投稿は本文に関係なく1件と数える。
CHANNEL_THEMES = {
    "旅行": "travel",
    "こんな本読みました": "reading",
    "不動産": "real_estate",
    "子育て": "parenting",
    "noteの話": "writing",
    "今日の運動": "exercise",
    "ダイエット": "exercise",
    "ハイキング倶楽部": "exercise",
    "ゲーム": "games",
    "麻雀部": "games",
    "グルメ・料理": "food",
    "ガーデニング・畑": "outdoor",
    "aiの話": "tech",
}


def discord_get(path: str, token: str, query: dict[str, str] | None = None) -> Any:
    url = f"{API_BASE}{path}" + (f"?{urlencode(query)}" if query else "")
    req = Request(url, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})
    while True:
        try:
            with urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                try:
                    time.sleep(float(json.loads(body).get("retry_after", 1.0)))
                except (ValueError, AttributeError):
                    time.sleep(1.0)
                continue
            raise RuntimeError(f"Discord API error {exc.code} for {path}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Discord API request failed for {path}: {exc}") from exc


def fetch_messages_since(token: str, channel_id: str, after_id: str) -> list[dict[str, Any]]:
    after = after_id
    messages: list[dict[str, Any]] = []
    while True:
        page = discord_get(f"/channels/{channel_id}/messages", token, {"limit": "100", "after": after})
        if not page:
            return messages
        page_sorted = sorted(page, key=lambda item: int(item["id"]))
        messages.extend(page_sorted)
        after = str(page_sorted[-1]["id"])
        if len(page_sorted) < 100:
            return messages


def collect_discord_counts(
    token: str, guild_id: str, nickname_by_user_id: dict[str, str], now: datetime,
) -> dict[str, dict[str, int]]:
    """nickname -> {theme: 件数}"""
    channels = discord_get(f"/guilds/{guild_id}/channels", token)
    id_by_name = {c.get("name"): str(c["id"]) for c in channels if c.get("type") == 0}
    after_id = snowflake_from_datetime(now - timedelta(days=DISCORD_WINDOW_DAYS))
    counts: dict[str, dict[str, int]] = {}
    names = [n for n in [*CHANNEL_CONTENT_TYPES, *DIGEST_EXTRA_CHANNEL_NAMES] if n not in EXCLUDED_CHANNELS]
    for channel_name in dict.fromkeys(names):
        channel_id = id_by_name.get(channel_name)
        if not channel_id:
            print(f"  channel not found, skipped: {channel_name}")
            continue
        try:
            messages = fetch_messages_since(token, channel_id, after_id)
        except RuntimeError as exc:
            print(f"  could not read {channel_name}: {exc}")
            continue
        for message in messages:
            nickname = nickname_by_user_id.get(str((message.get("author") or {}).get("id") or ""))
            if not nickname:
                continue
            themes = themes_in_text(str(message.get("content") or ""))
            if channel_name in CHANNEL_THEMES:
                themes.add(CHANNEL_THEMES[channel_name])
            for theme in themes:
                counts.setdefault(nickname, {}).setdefault(theme, 0)
                counts[nickname][theme] += 1
        print(f"  {channel_name}: {len(messages)} messages")
    return counts


def note_rss_url(profile_url: str) -> str | None:
    """https://note.com/<id>(/...) -> https://note.com/<id>/rss。記事URLやマガジンURLでも先頭のidを使う。"""
    parsed = urlparse(profile_url.strip())
    if not parsed.netloc.endswith("note.com"):
        return None
    first = next((part for part in parsed.path.split("/") if part), None)
    if not first or not re.fullmatch(r"[A-Za-z0-9_\-]+", first):
        return None
    return f"https://note.com/{first}/rss"


def fetch_note_items(rss_url: str, now: datetime) -> list[dict[str, str]]:
    req = Request(rss_url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as res:
        root = ET.fromstring(res.read())
    items = []
    cutoff = now - timedelta(days=NOTE_WINDOW_DAYS)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        description = re.sub(r"<[^>]+>", "", item.findtext("description") or "")
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if published < cutoff:
            continue
        items.append({"title": title, "text": f"{title} {description}", "published_at": published.isoformat()})
    return items


def collect_note_counts(
    note_urls: dict[str, list[str]], now: datetime,
) -> tuple[dict[str, dict[str, int]], dict[str, list[dict[str, str]]]]:
    counts: dict[str, dict[str, int]] = {}
    titles: dict[str, list[dict[str, str]]] = {}
    for nickname, urls in note_urls.items():
        rss_urls = list(dict.fromkeys(u for u in (note_rss_url(x) for x in urls) if u))
        for rss_url in rss_urls:
            try:
                items = fetch_note_items(rss_url, now)
            except (HTTPError, URLError, ET.ParseError, TimeoutError) as exc:
                print(f"  note RSS failed for {nickname} ({rss_url}): {exc}")
                continue
            for item in items:
                for theme in themes_in_text(item["text"]):
                    counts.setdefault(nickname, {}).setdefault(theme, 0)
                    counts[nickname][theme] += 1
            titles.setdefault(nickname, []).extend(
                {"title": i["title"], "published_at": i["published_at"]} for i in items
            )
            time.sleep(0.5)  # noteへの連続アクセスを控えめに
        if nickname in titles:
            titles[nickname] = sorted(titles[nickname], key=lambda t: t["published_at"], reverse=True)[:NOTE_MAX_TITLES]
    return counts, titles


def build_rows(
    nicknames: list[str],
    discord_counts: dict[str, dict[str, int]],
    note_counts: dict[str, dict[str, int]],
    note_titles: dict[str, list[dict[str, str]]],
    now: datetime,
) -> list[dict[str, Any]]:
    rows = []
    for nickname in nicknames:
        d = discord_counts.get(nickname, {})
        n = note_counts.get(nickname, {})
        theme_counts = {
            theme: {"discord": d.get(theme, 0), "note": n.get(theme, 0)} for theme in sorted(set(d) | set(n))
        }
        qualified = [
            theme for theme, c in theme_counts.items()
            if c["discord"] >= DISCORD_MIN_COUNT or c["note"] >= NOTE_MIN_COUNT
        ]
        score = {t: theme_counts[t]["discord"] + NOTE_WEIGHT * theme_counts[t]["note"] for t in qualified}
        recent_themes = sorted(qualified, key=lambda t: (-score[t], t))[:MAX_RECENT_THEMES]
        rows.append({
            "member_nickname": nickname,
            "recent_themes": recent_themes,
            "theme_counts": theme_counts,
            "recent_note_titles": note_titles.get(nickname, []),
            "updated_at": now.isoformat(),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect recent interest signals (Discord/note) for ゆるマッチング topics.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="Print the rows without writing to Supabase.")
    parser.add_argument("--skip-discord", action="store_true")
    parser.add_argument("--skip-note", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def get(path: str) -> Any:
        with urlopen(Request(f"{supabase_url}{path}", headers=headers), timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    now = datetime.now(timezone.utc)
    # 対象はゆるマッチングに参加中の人だけ(話題づくりにしか使わないため)
    nicknames = sorted(
        s["member_nickname"]
        for s in get("/rest/v1/member_matching_settings?select=member_nickname&opted_in=eq.true")
    )
    targets = set(nicknames)
    profiles = get("/rest/v1/member_profiles?select=nickname,discord_user_id&discord_user_id=not.is.null")
    nickname_by_user_id = {str(p["discord_user_id"]): p["nickname"] for p in profiles if p["nickname"] in targets}
    note_urls: dict[str, list[str]] = {}
    for link in get("/rest/v1/member_links?select=member_nickname,url"):
        if link["member_nickname"] in targets and "note.com" in (link.get("url") or ""):
            note_urls.setdefault(link["member_nickname"], []).append(link["url"])

    discord_counts: dict[str, dict[str, int]] = {}
    if not args.skip_discord:
        print(f"Discord (last {DISCORD_WINDOW_DAYS} days):")
        discord_counts = collect_discord_counts(
            require_env("DISCORD_BOT_TOKEN"), require_env("DISCORD_GUILD_ID"), nickname_by_user_id, now,
        )
    note_counts: dict[str, dict[str, int]] = {}
    note_titles: dict[str, list[dict[str, str]]] = {}
    if not args.skip_note:
        print(f"note (last {NOTE_WINDOW_DAYS} days): {len(note_urls)} members")
        note_counts, note_titles = collect_note_counts(note_urls, now)

    rows = build_rows(nicknames, discord_counts, note_counts, note_titles, now)
    for row in rows:
        if row["recent_themes"]:
            counts = row["theme_counts"]
            detail = ", ".join(f"{t}(D{counts[t]['discord']}/N{counts[t]['note']})" for t in row["recent_themes"])
            print(f"  {row['member_nickname']}: {detail}")
    print(f"{sum(1 for r in rows if r['recent_themes'])} / {len(rows)} members have recent themes")

    if args.dry_run:
        print("--dry-run: no writes to Supabase.")
        return 0
    req = Request(
        f"{supabase_url}/rest/v1/member_interest_signals?on_conflict=member_nickname",
        data=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60):
            pass
    except HTTPError as exc:
        raise SystemExit(f"Supabase upsert failed {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    return 0


if __name__ == "__main__":
    sys.exit(main())
