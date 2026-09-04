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
    parse_dt,
)

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-weekly-digest/0.1"
DEFAULT_EVENT_RAW = "tmp/community_events_raw.json"
DEFAULT_EVENT_CURATED = "data/community_events_curated.json"
DEFAULT_POSTS_RAW = "tmp/community_posts_raw.json"
MIN_POST_LENGTH = 20  # shorter than this reads as a one-line reaction, not a topic worth digesting
SENTENCE_END_CHARS = "。！？"


def trim_to_sentence(text: str, limit: int) -> str:
    """Cut text to at most `limit` chars, preferring the last full sentence.

    A plain text[:limit] slice (what clean_text's own `limit` arg does) often
    lands mid-sentence, which reads as a broken fragment rather than a summary
    -- e.g. "...ITチーム以外の人も興味があれば参...". Falls back to a hard cut
    with "…" only when no sentence boundary is found in a reasonable span.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    best_idx = max((window.rfind(ch) for ch in SENTENCE_END_CHARS), default=-1)
    if best_idx >= limit * 0.4:
        return window[: best_idx + 1]
    return window.rstrip() + "…"


def select_top_posts(
    posts: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    limit: int,
    display_limit: int = 280,
    max_per_channel: int = 1,
) -> list[dict[str, Any]]:
    """The most-reacted-to posts in the window, each with a clean_content field.

    Ranked by reaction_count (Discord's own "this got attention" signal, already
    present on fetched messages -- no extra API call needed) with post length as
    a tiebreaker for posts nobody reacted to yet.

    A high-traffic channel (e.g. 雑談) tends to rack up the most reactions purely
    from volume, which would otherwise fill every highlight slot and make the
    other ~28 scanned channels invisible even though they were considered. So
    the first pass takes at most `max_per_channel` post(s) per channel_name;
    only if that leaves slots unfilled (fewer distinct channels than `limit`)
    does a second post from the same channel get in.
    """
    candidates: list[dict[str, Any]] = []
    for item in posts:
        dt = parse_dt(item.get("posted_at"))
        if dt is None or not (start <= dt <= end):
            continue
        full_content = clean_text(str(item.get("content") or ""), limit=None)
        if len(full_content) < MIN_POST_LENGTH:
            continue
        candidates.append({
            **item,
            "clean_content": trim_to_sentence(full_content, display_limit),
            "reaction_count": int(item.get("reaction_count") or 0),
            "content_length": len(full_content),
        })
    candidates.sort(key=lambda item: (item["reaction_count"], item["content_length"]), reverse=True)

    selected: list[dict[str, Any]] = []
    leftover: list[dict[str, Any]] = []
    per_channel_count: dict[str, int] = {}
    for item in candidates:
        channel = str(item.get("channel_name") or "")
        if per_channel_count.get(channel, 0) < max_per_channel:
            selected.append(item)
            per_channel_count[channel] = per_channel_count.get(channel, 0) + 1
        else:
            leftover.append(item)
        if len(selected) >= limit:
            return selected[:limit]
    selected.extend(leftover[: limit - len(selected)])
    return selected[:limit]


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
    top_posts: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    max_highlights: int,
) -> str:
    period = period_label(start, end)
    lines = [f"🐾 {period}のF研を、のんびりのぞいてみたにゃ。今週はこんな話題があったよ。", ""]

    # Real gatherings first (they're already curated/deduped by collect_events), then
    # the most-reacted-to channel posts fill whatever highlight slots remain.
    highlights: list[tuple[str, str, str | None]] = []
    for activity in activities:
        summary = trim_to_sentence(activity.summary, 150)
        if not summary or not activity.permalink:
            continue
        highlights.append((activity.title, summary, activity.permalink))

    for post in top_posts:
        content_type = str(post.get("content_type") or "")
        label = POST_TYPE_LABELS.get(content_type) or str(post.get("channel_name") or "話題")
        highlights.append((label, post["clean_content"], post.get("discord_permalink")))

    if not highlights:
        lines.append("今週は大きな動きは少なめだったけど、いつも通りのんびりした空気が流れていたにゃ。")
    else:
        for title, summary, permalink in highlights[:max_highlights]:
            lines.append(f"・{title}：{summary}")
            if permalink:
                lines.append(f"  → {permalink}")

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
    parser.add_argument("--max-highlights", type=int, default=4, help="Max highlight bullets in the digest.")
    parser.add_argument("--post-to-discord", action="store_true", help="Post to DISCORD_DIGEST_CHANNEL_ID. No-op with a warning if unset.")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    end = datetime.now(JST)
    start = end - timedelta(days=args.days)

    raw_events = read_json(Path(args.events_raw), [])
    curated_events = read_json(Path(args.events_curated), [])
    posts_raw = read_json(Path(args.posts_raw), [])

    activities = collect_events(raw_events, curated_events, start, end, args.max_images_per_item)
    top_posts = select_top_posts(posts_raw, start, end, args.max_highlights)

    content = build_digest_content(activities, top_posts, start, end, args.max_highlights)
    print(content)
    print(f"\n--- {len(activities)} activities, {len(top_posts)} top posts considered ---")

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
