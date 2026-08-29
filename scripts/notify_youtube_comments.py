#!/usr/bin/env python3
"""Notify Discord about new public YouTube comments.

This uses a YouTube API key, not a YouTube login. On the first run it records
the currently visible comments without notifying, so old comments do not flood
Discord when the workflow is enabled.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-youtube-comment-notifier/0.1"
DISCORD_MESSAGE_LIMIT = 2000


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


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    req = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP error {exc.code} for {redact_url(url)}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"HTTP request failed for {redact_url(url)}: {exc}") from exc


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        [(key, "REDACTED" if key.lower() == "key" else value) for key, value in parse_qsl(parts.query)]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def discord_post(webhook_url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(req, timeout=30) as res:
            res.read()
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook error {exc.code}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord webhook request failed: {exc}") from exc


def discord_api(path: str, token: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{DISCORD_API_BASE}{path}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(req, timeout=30) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} for {path}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed for {path}: {exc}") from exc


def discord_dm_post(token: str, recipient_id: str, payload: dict[str, Any]) -> None:
    channel = discord_api("/users/@me/channels", token, {"recipient_id": recipient_id})
    channel_id = str(channel["id"])
    discord_api(f"/channels/{channel_id}/messages", token, payload)


def discord_channel_post(token: str, channel_id: str, payload: dict[str, Any]) -> None:
    discord_api(f"/channels/{channel_id}/messages", token, payload)


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_comment_threads(api_key: str, channel_id: str, max_results: int) -> list[dict[str, Any]]:
    query = {
        "key": api_key,
        "part": "snippet,replies",
        "allThreadsRelatedToChannelId": channel_id,
        "order": "time",
        "maxResults": str(max_results),
        "textFormat": "plainText",
    }
    payload = http_json(f"{YOUTUBE_API_BASE}/commentThreads?{urlencode(query)}")
    return list(payload.get("items") or [])


def collect_comments(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for thread in threads:
        thread_id = str(thread.get("id") or "")
        snippet = thread.get("snippet") or {}
        video_id = str(snippet.get("videoId") or "")
        top_level = (snippet.get("topLevelComment") or {}).get("snippet") or {}
        top_level_id = str((snippet.get("topLevelComment") or {}).get("id") or thread_id)
        if top_level_id and top_level:
            comments.append(build_comment(top_level_id, thread_id, video_id, top_level, is_reply=False))

        for reply in ((thread.get("replies") or {}).get("comments") or []):
            reply_id = str(reply.get("id") or "")
            reply_snippet = reply.get("snippet") or {}
            if reply_id and reply_snippet:
                comments.append(build_comment(reply_id, thread_id, video_id, reply_snippet, is_reply=True))

    return sorted(comments, key=lambda item: (item["published_at"], item["id"]))


def build_comment(
    comment_id: str,
    thread_id: str,
    video_id: str,
    snippet: dict[str, Any],
    *,
    is_reply: bool,
) -> dict[str, Any]:
    text = str(snippet.get("textOriginal") or snippet.get("textDisplay") or "").strip()
    return {
        "id": comment_id,
        "thread_id": thread_id,
        "video_id": video_id or str(snippet.get("videoId") or ""),
        "author_channel_id": str((snippet.get("authorChannelId") or {}).get("value") or ""),
        "author": str(snippet.get("authorDisplayName") or "unknown"),
        "text": html.unescape(text),
        "published_at": parse_datetime(str(snippet.get("publishedAt"))).isoformat(),
        "updated_at": parse_datetime(str(snippet.get("updatedAt") or snippet.get("publishedAt"))).isoformat(),
        "is_reply": is_reply,
    }


def youtube_watch_url(video_id: str, comment_id: str) -> str:
    if not video_id:
        return "https://www.youtube.com/"
    return f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}"


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def build_discord_payload(
    comment: dict[str, Any],
) -> dict[str, Any]:
    kind = "返信" if comment["is_reply"] else "コメント"
    url = youtube_watch_url(comment["video_id"], comment["id"])
    text = truncate(comment["text"] or "(本文なし)", 700)
    content = (
        f"YouTubeに新しい{kind}が付きました\n"
        f"投稿者: {comment['author']}\n"
        f"コメント: {text}\n"
        f"{url}"
    )
    return {"content": truncate(content, DISCORD_MESSAGE_LIMIT), "allowed_mentions": {"parse": []}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Discord notifications for new public YouTube comments.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--state-file", default="data/youtube_comment_notify_state.json")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--notify-existing",
        action="store_true",
        help="Notify comments found on the first run. By default the first run only initializes state.",
    )
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    api_key = require_env("YOUTUBE_API_KEY")
    channel_id = require_env("YOUTUBE_CHANNEL_ID")
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip() or None
    discord_bot_token = os.environ.get("DISCORD_BOT_TOKEN", "").strip() or None
    discord_channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip() or None
    discord_dm_user_id = os.environ.get("DISCORD_DM_USER_ID", "").strip() or None
    if not webhook_url and not (discord_bot_token and (discord_channel_id or discord_dm_user_id)):
        raise SystemExit(
            "Missing notification target: set DISCORD_WEBHOOK_URL, or set both "
            "DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID/DISCORD_DM_USER_ID."
        )

    state_path = Path(args.state_file)
    state = read_json_file(state_path, {})
    seen_ids = {str(item) for item in state.get("seen_comment_ids", [])}
    first_run = not bool(state.get("initialized"))

    threads = fetch_comment_threads(api_key, channel_id, args.max_results)
    comments = collect_comments(threads)
    current_ids = {comment["id"] for comment in comments}

    new_comments = [
        comment
        for comment in comments
        if comment["id"] not in seen_ids and comment.get("author_channel_id") != channel_id
    ]
    if first_run and not args.notify_existing:
        new_comments = []

    for comment in new_comments:
        payload = build_discord_payload(comment)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False))
        elif webhook_url:
            discord_post(webhook_url, payload)
        elif discord_channel_id:
            assert discord_bot_token
            discord_channel_post(discord_bot_token, discord_channel_id, payload)
        else:
            assert discord_bot_token and discord_dm_user_id
            discord_dm_post(discord_bot_token, discord_dm_user_id, payload)

    state_changed = first_run or bool(new_comments)
    if state_changed:
        next_seen_ids = sorted((seen_ids | current_ids), key=str)
        latest_seen_at = max((comment["published_at"] for comment in comments), default=state.get("latest_seen_at"))
        write_json_file(
            state_path,
            {
                "initialized": True,
                "youtube_channel_id": channel_id,
                "seen_comment_ids": next_seen_ids[-500:],
                "latest_seen_at": latest_seen_at,
                "last_checked_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    action = "initialized" if first_run and not args.notify_existing else "notified"
    print(f"{action}: {len(new_comments)} new comment(s); tracked {len(current_ids)} visible comment(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
