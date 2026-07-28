#!/usr/bin/env python3
"""Upsert curated community posts (books/travel/money+care consultations) into Supabase.

Reads tmp/community_posts_curated.json -- a human-reviewed selection produced
from tmp/community_posts_raw.json (see scripts/fetch_community_posts.py) with
title/summary decided in a Claude Code conversation, not a paid API call.
Skips any discord_message_id that was previously removed via the X button
(recorded in community_posts_history) so deleted posts are not silently
re-added on the next crawl. Safe to re-run: rows are upserted on
discord_message_id.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


REQUIRED_FIELDS = ("discord_message_id", "channel_name", "content_type", "summary", "posted_at", "discord_permalink")

# Only book recommendations are a single person's post. money_consultation and
# care_medical are usually multi-person discussion threads, so attributing the
# whole thread to whoever posted the first message would misrepresent it as
# solo content and would be misleading on that member's profile page.
SINGLE_AUTHOR_CONTENT_TYPES = {"book"}


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


def fetch_known_nicknames(supabase_url: str, service_role_key: str) -> set[str]:
    rows = supabase_request(
        "GET", f"{supabase_url}/rest/v1/member_profiles?select=nickname", service_role_key
    )
    return {row["nickname"] for row in (rows or [])}


def fetch_deleted_message_ids(supabase_url: str, service_role_key: str, message_ids: list[str]) -> set[str]:
    if not message_ids:
        return set()
    deleted: set[str] = set()
    # PostgREST in.() lists can get long; chunk to stay well under URL length limits.
    chunk_size = 200
    for i in range(0, len(message_ids), chunk_size):
        chunk = message_ids[i : i + chunk_size]
        ids_csv = ",".join(chunk)
        query = urlencode(
            {"discord_message_id": f"in.({ids_csv})", "action": "eq.delete", "select": "discord_message_id"},
            safe="(),.",
        )
        rows = supabase_request(
            "GET", f"{supabase_url}/rest/v1/community_posts_history?{query}", service_role_key
        )
        deleted.update(row["discord_message_id"] for row in (rows or []))
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert curated community posts into Supabase.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--curated", default="tmp/community_posts_curated.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    curated = json.loads(Path(args.curated).read_text(encoding="utf-8"))
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")

    for entry in curated:
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise SystemExit(f"Entry {entry.get('discord_message_id', '?')} missing required fields: {missing}")

    message_ids = [str(e["discord_message_id"]) for e in curated]
    deleted_ids = fetch_deleted_message_ids(supabase_url, service_role_key, message_ids) if not args.dry_run else set()
    known_nicknames = fetch_known_nicknames(supabase_url, service_role_key) if not args.dry_run else None

    rows = []
    skipped_deleted = 0
    unmatched_nicknames = 0
    for entry in curated:
        message_id = str(entry["discord_message_id"])
        if message_id in deleted_ids:
            skipped_deleted += 1
            continue
        member_nickname = entry.get("member_nickname")
        if member_nickname and entry["content_type"] not in SINGLE_AUTHOR_CONTENT_TYPES:
            member_nickname = None
        if known_nicknames is not None and member_nickname and member_nickname not in known_nicknames:
            print(f"Unmatched member_nickname {member_nickname!r} for {message_id} -- storing as unattributed.")
            member_nickname = None
            unmatched_nicknames += 1
        rows.append(
            {
                "member_nickname": member_nickname,
                "content_type": entry["content_type"],
                "title": entry.get("title"),
                "summary": entry["summary"],
                "discord_channel_name": entry["channel_name"],
                "discord_message_id": message_id,
                "discord_author_display_name": entry.get("discord_author_display_name"),
                "discord_permalink": entry["discord_permalink"],
                "posted_at": entry["posted_at"],
            }
        )

    print(
        f"Prepared {len(rows)} rows to upsert "
        f"({skipped_deleted} skipped as previously deleted, {unmatched_nicknames} unmatched member_nickname)."
    )

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if rows:
        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/community_posts?on_conflict=discord_message_id",
            service_role_key,
            body=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print("Upserted community_posts.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
