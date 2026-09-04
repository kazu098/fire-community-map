#!/usr/bin/env python3
"""Post a weekly digest of F研's Discord activity, in ふぁいにゃ's voice.

Unlike scripts/generate_note_activity_draft.py (a long, editor-reviewed note
article), this is a short, casual summary meant for busy members: "here's
what happened this week" as a single Discord message, posted directly by
ふぁいにゃ (see docs/fainya-persona.md) rather than drafted for a human to
paste. Reuses generate_note_activity_draft's event/post collection so the
"what counts as an activity" rules stay in one place.

Run scripts/fetch_community_events.py and scripts/fetch_community_posts.py
first to produce the raw JSON this script reads.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from generate_note_activity_draft import (
    JST,
    POST_TYPE_LABELS,
    Activity,
    clean_text,
    collect_events,
    collect_post_topics,
)

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-weekly-digest/0.1"
DEFAULT_EVENT_RAW = "tmp/community_events_raw.json"
DEFAULT_EVENT_CURATED = "data/community_events_curated.json"
DEFAULT_POSTS_RAW = "tmp/community_posts_raw.json"

# Same rendering order as generate_note_activity_draft's editorial template,
# minus the section headings -- here each just becomes one digest line.
TOPIC_ORDER = (
    "book", "travel", "question_consultation", "money_consultation",
    "note", "care_medical", "parenting", "real_estate",
)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def period_label(start: datetime, end: datetime) -> str:
    if start.year == end.year:
        return f"{start.month}月{start.day}日〜{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日〜{end.year}年{end.month}月{end.day}日"


def build_digest_content(
    activities: list[Activity],
    post_topics: dict[str, list[dict[str, Any]]],
    start: datetime,
    end: datetime,
    max_lines: int,
) -> str:
    period = period_label(start, end)
    lines = [f"🐾 {period}のF研を、のんびりのぞいてみたにゃ。今週はこんな話題があったよ。", ""]

    highlight_lines: list[str] = []
    for activity in activities:
        summary = clean_text(activity.summary, 50)
        if not summary:
            continue
        highlight_lines.append(f"・{activity.title}：{summary}")

    for content_type in TOPIC_ORDER:
        items = post_topics.get(content_type)
        if not items:
            continue
        label = POST_TYPE_LABELS.get(content_type, content_type)
        example = clean_text(str(items[0].get("clean_content") or ""), 40)
        count = len(items)
        highlight_lines.append(f"・{label}：{count}件の投稿があったにゃ（例:「{example}」）")

    if not highlight_lines:
        lines.append("今週は大きな動きは少なめだったけど、いつも通りのんびりした空気が流れていたにゃ。")
    else:
        lines.extend(highlight_lines[:max_lines])

    lines.append("")
    lines.append("気になる話題があったら、ぜひチャンネルをのぞいてみてね。また来週、のんびりまとめるにゃ。")
    return "\n".join(lines)


def discord_post(channel_id: str, token: str, content: str) -> str | None:
    body = {"content": content, "allowed_mentions": {"parse": []}}
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as res:
            payload = json.loads(res.read().decode("utf-8"))
            return payload.get("id")
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} posting to channel {channel_id}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed posting to channel {channel_id}: {exc}") from exc


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate (and optionally post) the weekly F研 digest.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--days", type=int, default=7, help="Number of trailing days to summarize.")
    parser.add_argument("--events-raw", default=DEFAULT_EVENT_RAW)
    parser.add_argument("--events-curated", default=DEFAULT_EVENT_CURATED)
    parser.add_argument("--posts-raw", default=DEFAULT_POSTS_RAW)
    parser.add_argument("--max-images-per-item", type=int, default=0)
    parser.add_argument("--post-topic-limit", type=int, default=8)
    parser.add_argument("--max-lines", type=int, default=8, help="Max highlight bullets in the digest.")
    parser.add_argument("--post-to-discord", action="store_true", help="Post to DISCORD_DIGEST_CHANNEL_ID. No-op with a warning if unset.")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    end = datetime.now(JST)
    start = end - timedelta(days=args.days)

    raw_events = read_json(Path(args.events_raw), [])
    curated_events = read_json(Path(args.events_curated), [])
    posts_raw = read_json(Path(args.posts_raw), [])

    activities = collect_events(raw_events, curated_events, start, end, args.max_images_per_item)
    post_topics = collect_post_topics(posts_raw, start, end, args.post_topic_limit)

    content = build_digest_content(activities, post_topics, start, end, args.max_lines)
    print(content)
    print(f"\n--- {len(activities)} activities, {sum(len(v) for v in post_topics.values())} topic candidates ---")

    if not args.post_to_discord:
        return 0

    channel_id = os.environ.get("DISCORD_DIGEST_CHANNEL_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not channel_id or not bot_token:
        print("DISCORD_DIGEST_CHANNEL_ID or DISCORD_BOT_TOKEN is not set. Skipping Discord post.")
        return 0

    message_id = discord_post(channel_id, bot_token, content)
    print(f"Posted to Discord channel {channel_id} (message {message_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
