#!/usr/bin/env python3
"""Fetch raw Discord messages from event-related channels.

This collects source messages only. Curated event rows for the UI are created
from the raw JSON and loaded with scripts/load_community_events.py.
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
USER_AGENT = "fire-community-map-community-events-sync/0.1"

EVENT_CHANNEL_NAMES = (
    "オンラインイベント",
    "オフ会",
    "イベント用フォーラム",
    "1周年記念オフ会",
    "イタリアンオフ会",
    "9月13日-文学フリマ大阪",
)

SCHEDULED_EVENT_STATUS = {
    1: "scheduled",
    2: "active",
    3: "completed",
    4: "cancelled",
}

SCHEDULED_EVENT_ENTITY_TYPE = {
    1: "stage_instance",
    2: "voice",
    3: "external",
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
    req = Request(url, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})
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


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def channel_matches(channels: list[dict[str, Any]], channel_name: str) -> list[dict[str, Any]]:
    normalized = channel_name.lstrip("#")
    return [
        c for c in channels
        if c.get("type") in {0, 5, 15} and c.get("name") in {normalized, channel_name}
    ]


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


def fetch_forum_threads(token: str, channel_id: str) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    active = discord_get(f"/channels/{channel_id}/threads/active", token)
    threads.extend(active.get("threads", []))

    before: str | None = None
    while True:
        query = {"limit": "100"}
        if before:
            query["before"] = before
        page = discord_get(f"/channels/{channel_id}/threads/archived/public", token, query)
        page_threads = page.get("threads", [])
        threads.extend(page_threads)
        if not page.get("has_more") or not page_threads:
            break
        before = min(str(t["archive_timestamp"]) for t in page_threads if t.get("archive_timestamp"))
        if not before:
            break
    return threads


def fetch_scheduled_events(token: str, guild_id: str) -> list[dict[str, Any]]:
    return discord_get(
        f"/guilds/{guild_id}/scheduled-events",
        token,
        {"with_user_count": "true"},
    )


def message_entry(
    message: dict[str, Any],
    channel_name: str,
    guild_id: str,
    channel_id: str,
    name_map: dict[str, str],
    thread_name: str | None = None,
) -> dict[str, Any]:
    author = message.get("author", {})
    member = message.get("member")
    author_name = display_name(author, member)
    return {
        "discord_message_id": str(message["id"]),
        "channel_name": channel_name,
        "thread_name": thread_name,
        "discord_author_display_name": author_name,
        "member_nickname": name_map.get(author_name, author_name),
        "content": str(message.get("content") or "").strip(),
        "embeds": message.get("embeds") or [],
        "attachments": [
            {
                "filename": item.get("filename"),
                "content_type": item.get("content_type"),
                "url": item.get("url"),
            }
            for item in (message.get("attachments") or [])
        ],
        "posted_at": datetime.fromisoformat(str(message["timestamp"]).replace("Z", "+00:00")).isoformat(),
        "discord_permalink": f"https://discord.com/channels/{guild_id}/{channel_id}/{message['id']}",
    }


def scheduled_event_entry(event: dict[str, Any], guild_id: str, channel_names_by_id: dict[str, str]) -> dict[str, Any]:
    event_id = str(event["id"])
    channel_id = str(event.get("channel_id") or "")
    location = (event.get("entity_metadata") or {}).get("location")
    return {
        "discord_message_id": f"scheduled_event:{event_id}",
        "discord_event_id": event_id,
        "source_type": "scheduled_event",
        "channel_name": channel_names_by_id.get(channel_id),
        "name": str(event.get("name") or ""),
        "description": str(event.get("description") or "").strip(),
        "scheduled_start_time": event.get("scheduled_start_time"),
        "scheduled_end_time": event.get("scheduled_end_time"),
        "status": SCHEDULED_EVENT_STATUS.get(event.get("status"), str(event.get("status"))),
        "entity_type": SCHEDULED_EVENT_ENTITY_TYPE.get(event.get("entity_type"), str(event.get("entity_type"))),
        "channel_id": channel_id or None,
        "location": location,
        "user_count": event.get("user_count"),
        "posted_at": event.get("scheduled_start_time"),
        "discord_permalink": f"https://discord.com/events/{guild_id}/{event_id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch raw Discord event messages.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--name-map", default="config/member_discord_name_map.csv")
    parser.add_argument("--output", default="tmp/community_events_raw.json")
    parser.add_argument("--state-file", default="data/community_events_sync_state.json")
    parser.add_argument("--channel", action="append", dest="channels", help="Discord channel name to fetch. Can be repeated.")
    parser.add_argument("--skip-scheduled-events", action="store_true")
    parser.add_argument("--since", type=parse_datetime, help="Initial fetch start time for channels without sync state.")
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")

    channels = discord_get(f"/guilds/{guild_id}/channels", token)
    channel_names_by_id = {str(c["id"]): str(c.get("name") or "") for c in channels}
    target_names = tuple(args.channels or EVENT_CHANNEL_NAMES)
    name_map = read_name_map(Path(args.name_map))

    state_path = Path(args.state_file)
    state = {} if args.reset_state else read_json_file(state_path, {})
    existing_raw = read_json_file(Path(args.output), [])
    if not isinstance(existing_raw, list):
        raise SystemExit(f"{args.output} must contain a JSON array.")
    by_message_id = {str(e["discord_message_id"]): e for e in existing_raw if e.get("discord_message_id")}

    next_state = dict(state)
    summary: dict[str, Any] = {}

    for channel_name in target_names:
        matches = channel_matches(channels, channel_name)
        if not matches:
            summary[channel_name] = {"error": "channel not found"}
            continue

        channel_count = 0
        for channel in matches:
            channel_id = str(channel["id"])
            state_key = f"{channel_name}:{channel_id}"
            channel_state = state.get(state_key, {})
            last_scanned_message_id = channel_state.get("last_scanned_message_id")
            if last_scanned_message_id:
                after_id = str(last_scanned_message_id)
            elif args.since:
                after_id = snowflake_from_datetime(args.since)
            else:
                raise SystemExit(
                    f"No sync state for channel '{channel_name}'. Pass --since 2026-01-01T00:00:00+09:00 for its first run."
                )

            try:
                messages = fetch_messages(token, channel_id, after_id) if channel.get("type") != 15 else []
            except RuntimeError as exc:
                summary[state_key] = {"error": str(exc)}
                continue
            for message in messages:
                entry = message_entry(message, channel_name, guild_id, channel_id, name_map)
                by_message_id[entry["discord_message_id"]] = entry
                channel_count += 1

            newest_ids = [str(m["id"]) for m in messages]
            if channel.get("type") == 15:
                try:
                    threads = fetch_forum_threads(token, channel_id)
                except RuntimeError as exc:
                    summary[state_key] = {"error": str(exc)}
                    continue
                for thread in threads:
                    thread_id = str(thread["id"])
                    if int(thread_id) <= int(after_id):
                        continue
                    try:
                        thread_messages = fetch_messages(token, thread_id, snowflake_from_datetime(args.since)) if args.since else []
                    except RuntimeError as exc:
                        summary[f"{state_key}:{thread_id}"] = {"error": str(exc)}
                        continue
                    for message in thread_messages:
                        entry = message_entry(
                            message,
                            channel_name,
                            guild_id,
                            thread_id,
                            name_map,
                            thread_name=str(thread.get("name") or ""),
                        )
                        by_message_id[entry["discord_message_id"]] = entry
                        channel_count += 1
                        newest_ids.append(str(message["id"]))
                    newest_ids.append(thread_id)

            newest_scanned_id = max(newest_ids, key=int, default=str(after_id))
            next_state[state_key] = {
                "channel_id": channel_id,
                "last_scanned_message_id": newest_scanned_id,
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }

        summary[channel_name] = {"new_or_updated": channel_count, "matches": len(matches)}

    scheduled_count = 0
    if not args.skip_scheduled_events:
        try:
            for event in fetch_scheduled_events(token, guild_id):
                entry = scheduled_event_entry(event, guild_id, channel_names_by_id)
                by_message_id[f"scheduled_event:{entry['discord_event_id']}"] = entry
                scheduled_count += 1
            summary["scheduled_events"] = {"new_or_updated": scheduled_count}
        except RuntimeError as exc:
            summary["scheduled_events"] = {"error": str(exc)}

    raw_entries = sorted(by_message_id.values(), key=lambda e: e.get("posted_at") or "", reverse=True)
    write_json_file(Path(args.output), raw_entries)
    write_json_file(state_path, next_state)

    print(json.dumps({"channels": summary, "total_entries": len(raw_entries), "output": args.output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
