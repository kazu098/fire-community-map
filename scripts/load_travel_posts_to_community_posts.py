#!/usr/bin/env python3
"""Upsert local travel map posts into Supabase community_posts."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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


def supabase_request(method: str, url: str, service_role_key: str, body: Any = None, prefer: str | None = None) -> Any:
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


def read_name_map(path: Path) -> dict[str, str]:
    """discord_display_name -> form_nickname, from member_discord_name_map.csv."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            row["discord_display_name"].strip(): row["form_nickname"].strip()
            for row in csv.DictReader(f)
            if row.get("discord_display_name") and row.get("form_nickname")
        }


def fetch_known_nicknames(supabase_url: str, service_role_key: str) -> set[str]:
    rows = supabase_request(
        "GET", f"{supabase_url}/rest/v1/member_profiles?select=nickname", service_role_key
    )
    return {row["nickname"] for row in (rows or [])}


def fetch_deleted_message_ids(supabase_url: str, service_role_key: str, message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    deleted: set[str] = set()
    for i in range(0, len(message_ids), 200):
        chunk = message_ids[i : i + 200]
        query = urlencode(
            {"discord_message_id": f"in.({','.join(chunk)})", "action": "eq.delete", "select": "discord_message_id"},
            safe="(),.",
        )
        rows = supabase_request(
            "GET", f"{supabase_url}/rest/v1/community_posts_history?{query}", service_role_key
        )
        deleted.update(row["discord_message_id"] for row in (rows or []))
    return deleted


def fetch_remote_travel_message_ids(supabase_url: str, service_role_key: str) -> set[str]:
    rows = supabase_request(
        "GET",
        f"{supabase_url}/rest/v1/community_posts?select=discord_message_id&content_type=eq.travel",
        service_role_key,
    )
    return {str(row["discord_message_id"]) for row in (rows or []) if row.get("discord_message_id")}


def unlink_unlisted_travel_posts(
    supabase_url: str,
    service_role_key: str,
    message_ids: list[str],
) -> None:
    for i in range(0, len(message_ids), 200):
        chunk = message_ids[i : i + 200]
        query = urlencode(
            {"discord_message_id": f"in.({','.join(chunk)})", "content_type": "eq.travel"},
            safe="(),.",
        )
        supabase_request(
            "PATCH",
            f"{supabase_url}/rest/v1/community_posts?{query}",
            service_role_key,
            body={"member_nickname": None},
            prefer="return=minimal",
        )


def title_for_post(post: dict[str, Any]) -> str:
    place = "".join(str(v) for v in (post.get("prefecture"), post.get("municipality_optional")) if v)
    label = "グルメ投稿" if post.get("discord_channel_name") == "グルメ・料理" else "旅行投稿"
    return f"{place or '旅先'}の{label}"


def permalink(guild_id: str, channel_id: str, message_id: str) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def channel_ids_from_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("channels"):
        return {
            channel_name: str(channel_state["channel_id"])
            for channel_name, channel_state in state["channels"].items()
            if channel_state.get("channel_id")
        }
    if state.get("channel_id"):
        return {"旅行": str(state["channel_id"])}
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert data/travel_posts.json into community_posts.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--input", default="data/travel_posts.json")
    parser.add_argument("--name-map", default="config/member_discord_name_map.csv")
    parser.add_argument("--channel-name", default="旅行")
    parser.add_argument("--channel-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL").rstrip("/")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    guild_id = require_env("DISCORD_GUILD_ID")
    channel_ids = channel_ids_from_state(Path("data/travel_sync_state.json"))
    if args.channel_id:
        channel_ids[args.channel_name] = str(args.channel_id)

    posts = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(posts, list):
        raise SystemExit(f"{args.input} must contain a JSON array.")

    name_map = read_name_map(Path(args.name_map))
    known_nicknames = fetch_known_nicknames(supabase_url, service_role_key)
    message_ids = [str(post["discord_message_id"]) for post in posts if post.get("discord_message_id")]
    deleted_ids = fetch_deleted_message_ids(supabase_url, service_role_key, message_ids)
    remote_ids = fetch_remote_travel_message_ids(supabase_url, service_role_key)

    rows: list[dict[str, Any]] = []
    skipped_deleted = 0
    unmatched_nicknames = 0
    for post in posts:
        message_id = str(post.get("discord_message_id") or "")
        if not message_id:
            continue
        if message_id in deleted_ids:
            skipped_deleted += 1
            continue

        display_name = str(post.get("nickname") or "").strip()
        member_nickname = name_map.get(display_name, display_name)
        if member_nickname not in known_nicknames:
            member_nickname = None
            unmatched_nicknames += 1

        rows.append(
            {
                "member_nickname": member_nickname,
                "content_type": "travel",
                "title": title_for_post(post),
                "summary": str(post.get("comment") or title_for_post(post)).strip(),
                "discord_channel_name": str(post.get("discord_channel_name") or args.channel_name),
                "discord_message_id": message_id,
                "discord_author_display_name": display_name or None,
                "discord_permalink": post.get("discord_permalink")
                or permalink(guild_id, channel_ids.get(str(post.get("discord_channel_name") or args.channel_name), ""), message_id),
                "posted_at": post["posted_at"],
            }
        )

    print(
        f"Prepared {len(rows)} travel rows "
        f"({skipped_deleted} skipped as previously deleted, {unmatched_nicknames} unmatched member_nickname)."
    )
    row_ids = {row["discord_message_id"] for row in rows}
    unlisted_remote_ids = sorted(remote_ids - row_ids)
    print(f"Remote travel rows to unlink from member details: {len(unlisted_remote_ids)}")
    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        if unlisted_remote_ids:
            print(json.dumps({"unlink_discord_message_ids": unlisted_remote_ids}, ensure_ascii=False, indent=2))
        return 0

    if rows:
        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/community_posts?on_conflict=discord_message_id",
            service_role_key,
            body=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print("Upserted travel community_posts.")
    if unlisted_remote_ids:
        unlink_unlisted_travel_posts(supabase_url, service_role_key, unlisted_remote_ids)
        print("Unlinked unlisted travel community_posts from member details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
