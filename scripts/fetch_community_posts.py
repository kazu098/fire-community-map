#!/usr/bin/env python3
"""Fetch raw Discord messages from the community "stock content" channels.

Collection only -- no summarization, no LLM calls, no API billing. Writes the
raw messages to a JSON file (default tmp/community_posts_raw.json) for a human
(with Claude Code, under the existing subscription, not the API) to review and
curate into tmp/community_posts_curated.json, which scripts/load_community_posts.py
then upserts into Supabase. Mirrors the fetch_self_intros.py -> hand-curated
dict -> load_member_profiles.py pattern already used in this repo.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://discord.com/api/v10"
DISCORD_EPOCH = 1420070400000
USER_AGENT = "fire-community-map-community-posts-sync/0.1"

# Channel name -> content_type. Edit here to add more channels later.
CHANNEL_CONTENT_TYPES = {
    "お金の話・相談": "money_consultation",
    "こんな本読みました": "book",
    "旅行": "travel",
    "介護・医療": "care_medical",
}


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


def discord_get(path: str, token: str, query: dict[str, str] | None = None) -> Any:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    req = Request(
        url,
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} for {path}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed for {path}: {exc}") from exc


def snowflake_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    millis = int(dt.timestamp() * 1000)
    return str((millis - DISCORD_EPOCH) << 22)


def parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Datetime must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def find_channel_id(channels: list[dict[str, Any]], channel_name: str) -> str:
    normalized = channel_name.lstrip("#")
    matches = [c for c in channels if c.get("type") == 0 and c.get("name") in {normalized, channel_name}]
    if len(matches) != 1:
        names = ", ".join(sorted(str(c.get("name")) for c in channels if c.get("type") == 0))
        raise SystemExit(f"Could not uniquely find channel '{channel_name}'. Text channels: {names}")
    return str(matches[0]["id"])


def read_name_map(path: Path) -> dict[str, str]:
    """discord_display_name -> form_nickname, reversed from member_discord_name_map.csv."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            row["discord_display_name"].strip(): row["form_nickname"].strip()
            for row in csv.DictReader(f)
            if row.get("discord_display_name") and row.get("form_nickname")
        }


def display_name(author: dict[str, Any], member: dict[str, Any] | None) -> str:
    if member and member.get("nick"):
        return str(member["nick"])
    return str(author.get("global_name") or author.get("username") or "unknown")


def fetch_messages(token: str, channel_id: str, after_id: str) -> list[dict[str, Any]]:
    after = after_id
    messages: list[dict[str, Any]] = []
    while True:
        page = discord_get(f"/channels/{channel_id}/messages", token, {"limit": "100", "after": after})
        if not page:
            break
        page_sorted = sorted(page, key=lambda item: int(item["id"]))
        messages.extend(page_sorted)
        after = str(page_sorted[-1]["id"])
        if len(page_sorted) < 100:
            break
    return messages


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_raw_entry(
    message: dict[str, Any],
    channel_name: str,
    content_type: str,
    guild_id: str,
    channel_id: str,
    name_map: dict[str, str],
) -> dict[str, Any]:
    author = message.get("author", {})
    member = message.get("member")
    author_name = display_name(author, member)
    content = str(message.get("content") or "").strip()
    posted_at = datetime.fromisoformat(str(message["timestamp"]).replace("Z", "+00:00"))
    return {
        "discord_message_id": str(message["id"]),
        "channel_name": channel_name,
        "content_type": content_type,
        "discord_author_display_name": author_name,
        "member_nickname": name_map.get(author_name),
        "content": content,
        "posted_at": posted_at.isoformat(),
        "discord_permalink": f"https://discord.com/channels/{guild_id}/{channel_id}/{message['id']}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch raw messages from the community stock-content Discord channels."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--name-map", default="config/member_discord_name_map.csv")
    parser.add_argument("--output", default="tmp/community_posts_raw.json")
    parser.add_argument("--state-file", default="data/community_posts_sync_state.json")
    parser.add_argument(
        "--since",
        type=parse_datetime,
        help="Initial fetch start time, applied to any channel with no existing sync state.",
    )
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")

    name_map = read_name_map(Path(args.name_map))
    channels = discord_get(f"/guilds/{guild_id}/channels", token)

    state_path = Path(args.state_file)
    state = {} if args.reset_state else read_json_file(state_path, {})

    existing_raw = read_json_file(Path(args.output), [])
    if not isinstance(existing_raw, list):
        raise SystemExit(f"{args.output} must contain a JSON array.")
    by_message_id = {str(e["discord_message_id"]): e for e in existing_raw if e.get("discord_message_id")}

    next_state = dict(state)
    summary: dict[str, Any] = {}

    for channel_name, content_type in CHANNEL_CONTENT_TYPES.items():
        channel_id = find_channel_id(channels, channel_name)
        channel_state = state.get(channel_name, {})
        last_scanned_message_id = channel_state.get("last_scanned_message_id")
        if last_scanned_message_id:
            after_id = str(last_scanned_message_id)
        elif args.since:
            after_id = snowflake_from_datetime(args.since)
        else:
            raise SystemExit(
                f"No sync state for channel '{channel_name}'. Pass --since 2026-01-01T00:00:00+09:00 for its first run."
            )

        messages = fetch_messages(token, channel_id, after_id)
        new_count = 0
        for message in messages:
            entry = build_raw_entry(message, channel_name, content_type, guild_id, channel_id, name_map)
            by_message_id[entry["discord_message_id"]] = entry
            new_count += 1

        newest_scanned_id = max((str(m["id"]) for m in messages), key=int, default=str(after_id))
        next_state[channel_name] = {
            "channel_id": str(channel_id),
            "last_scanned_message_id": newest_scanned_id,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        summary[channel_name] = {"messages_scanned": len(messages), "new_or_updated": new_count}

    raw_entries = sorted(by_message_id.values(), key=lambda e: e["posted_at"], reverse=True)
    write_json_file(Path(args.output), raw_entries)
    write_json_file(state_path, next_state)

    print(json.dumps({"channels": summary, "total_entries": len(raw_entries), "output": args.output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
