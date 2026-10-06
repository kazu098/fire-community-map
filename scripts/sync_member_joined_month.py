#!/usr/bin/env python3
"""Fill member_profiles.joined_month (F研の入会時期, issue #324) from the self-intro channel.

The 入会時期 shown on a member's profile is the month of their FIRST self-introduction post
in the Discord self-intro channel (members who re-posted an updated intro keep the month of
the original one). This walks the whole channel, takes each author's earliest message that
looks like a self-introduction (fetch_self_intros.is_self_intro), and matches it to a member
by member_profiles.discord_user_id.

Members who never posted a self-introduction get no joined_month (the profile shows nothing;
they can pick one themselves on the map). A value the member set themselves
(joined_month_source = 'member') is never overwritten.

Run weekly from .github/workflows/refresh-member-avatars.yml so new members get theirs within
a week. --dry-run prints the changes without writing.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import fetch_self_intros as intros

DEFAULT_SELF_INTRO_CHANNEL_ID = "1389923387887063171"
JST = ZoneInfo("Asia/Tokyo")


def supabase_request(supabase_url: str, service_role_key: str, path: str, method: str = "GET", body: Any = None) -> Any:
    req = Request(
        f"{supabase_url}/rest/v1/{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        method=method,
    )
    with urlopen(req, timeout=30) as res:
        raw = res.read().decode("utf-8")
        return json.loads(raw) if raw else None


def month_of(timestamp: str) -> date:
    """First day of the JST month the Discord message timestamp falls in."""
    posted = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(JST)
    return date(posted.year, posted.month, 1)


def earliest_intro_months(messages: list[dict[str, Any]]) -> dict[str, date]:
    earliest: dict[str, date] = {}
    # fetch_all_messages returns messages oldest first, so the first hit per author wins.
    for message in messages:
        author_id = str((message.get("author") or {}).get("id") or "")
        if not author_id or author_id in earliest or not intros.is_self_intro(message):
            continue
        earliest[author_id] = month_of(str(message["timestamp"]))
    return earliest


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill member_profiles.joined_month from the first self-intro post.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--channel-id", default=DEFAULT_SELF_INTRO_CHANNEL_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    intros.load_dotenv(Path(args.env_file))
    discord_token = intros.require_env("DISCORD_BOT_TOKEN")
    supabase_url = intros.require_env("SUPABASE_URL")
    service_role_key = intros.require_env("SUPABASE_SERVICE_ROLE_KEY")

    messages = intros.fetch_all_messages(discord_token, args.channel_id)
    months_by_author = earliest_intro_months(messages)
    print(f"{len(messages)} messages, {len(months_by_author)} authors with a self-intro.")

    members = supabase_request(
        supabase_url, service_role_key,
        "member_profiles?select=nickname,discord_user_id,joined_month,joined_month_source&discord_user_id=not.is.null",
    )
    updated = 0
    for member in members:
        if member.get("joined_month_source") == "member":
            continue
        month = months_by_author.get(str(member["discord_user_id"]))
        if not month or member.get("joined_month") == month.isoformat():
            continue
        print(f"{member['nickname']}: {member.get('joined_month')} -> {month.isoformat()}")
        updated += 1
        if args.dry_run:
            continue
        supabase_request(
            supabase_url, service_role_key,
            f"member_profiles?nickname=eq.{quote(member['nickname'])}",
            method="PATCH",
            body={"joined_month": month.isoformat(), "joined_month_source": "self_intro"},
        )
    print(f"{updated} member(s) {'would be ' if args.dry_run else ''}updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
