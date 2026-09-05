#!/usr/bin/env python3
"""Confirm ゆるマッチング schedule proposals and manage their temporary voice channels.

Follow-up to scripts/run_member_matching.py's date-proposal reaction poll (see
supabase/member_match_schedules.sql for the design background: itチーム
Discord proposal from memeto0531, 2026-09-05). Two independent passes, run
together on a schedule:

1. Confirm: for each `proposed` schedule, count how many of the *matched
   group's* members (not just anyone) reacted to each of the 3 date options.
   Once SCHEDULE_CONFIRM_THRESHOLD (3 of 4) is reached on some option, that
   date is confirmed -- ties broken by earliest date -- a confirmation
   message is posted, and a temporary voice channel is created with
   permission overwrites scoped to just that group (denied for @everyone).
   A schedule whose last proposed date has passed with no option reaching
   the threshold is marked `expired` instead (no channel, no announcement --
   quiet by design, this is a low-stakes opt-in feature).
2. Cleanup: for each `confirmed` schedule whose event time is more than
   VOICE_CHANNEL_CLEANUP_BUFFER_HOURS in the past and whose voice channel
   hasn't been deleted yet, delete the channel.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import run_member_matching as matching

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-member-matching-schedules/0.1"
VOICE_CHANNEL_CLEANUP_BUFFER_HOURS = 4
# VIEW_CHANNEL (0x400) + CONNECT (0x100000): enough to see and join the temporary
# voice channel, nothing more.
VOICE_CHANNEL_PERMISSION_BITS = 0x400 | 0x100000


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


def discord_get(url: str, token: str) -> Any:
    req = Request(url, headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} for GET {url}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed for GET {url}: {exc}") from exc


def fetch_reactors(channel_id: str, message_id: str, emoji: str, token: str) -> set[str]:
    """Discord user ids who reacted with `emoji` on this message (bot's own reaction excluded
    by the caller, since it always adds one of these to make the option clickable)."""
    encoded_emoji = quote(emoji)
    users = discord_get(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}?limit=100",
        token,
    )
    return {str(u["id"]) for u in users}


def create_voice_channel(guild_id: str, name: str, member_user_ids: list[str], token: str) -> str:
    overwrites = [{"id": guild_id, "type": 0, "allow": "0", "deny": str(VOICE_CHANNEL_PERMISSION_BITS)}]
    overwrites.extend(
        {"id": user_id, "type": 1, "allow": str(VOICE_CHANNEL_PERMISSION_BITS), "deny": "0"}
        for user_id in member_user_ids
    )
    body = {"name": name, "type": 2, "permission_overwrites": overwrites}
    req = Request(
        f"{DISCORD_API_BASE}/guilds/{guild_id}/channels",
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
            return str(json.loads(res.read().decode("utf-8"))["id"])
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} creating voice channel: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed creating voice channel: {exc}") from exc


def delete_channel(channel_id: str, token: str) -> None:
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}",
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
        method="DELETE",
    )
    try:
        with urlopen(req, timeout=30):
            pass
    except HTTPError as exc:
        if exc.code == 404:
            return  # already gone (manually deleted, etc.) -- treat as success
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} deleting channel {channel_id}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed deleting channel {channel_id}: {exc}") from exc


def confirm_schedules(
    supabase_url: str,
    service_role_key: str,
    channel_id: str,
    guild_id: str,
    bot_token: str,
    now: datetime,
    dry_run: bool,
) -> None:
    headers_select = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def get(path: str) -> Any:
        req = Request(f"{supabase_url}{path}", headers=headers_select, method="GET")
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    schedules = get("/rest/v1/member_match_schedules?select=id,group_id,proposed_dates,discord_message_id&status=eq.proposed")
    if not schedules:
        print("No proposed schedules to check.")
        return

    guild_display_name_ids = matching.fetch_guild_member_ids_by_display_name(bot_token, guild_id)
    name_overrides = matching.load_discord_name_overrides(Path("config/member_discord_name_map.csv"))

    for schedule in schedules:
        group_id = schedule["group_id"]
        members = get(f"/rest/v1/member_match_group_members?group_id=eq.{group_id}&select=member_nickname")
        nicknames = [m["member_nickname"] for m in members]
        discord_user_ids = matching.resolve_discord_user_ids(nicknames, guild_display_name_ids, name_overrides)
        group_user_ids = set(discord_user_ids.values())

        proposed_dates = [datetime.fromisoformat(d) for d in schedule["proposed_dates"]]
        message_id = schedule["discord_message_id"]

        counts: list[tuple[datetime, int]] = []
        for date, emoji in zip(proposed_dates, matching.DATE_OPTION_EMOJI):
            reactors = fetch_reactors(channel_id, message_id, emoji, bot_token)
            counts.append((date, len(reactors & group_user_ids)))

        best_date, best_count = max(counts, key=lambda item: (item[1], -item[0].timestamp()))

        if best_count >= matching.SCHEDULE_CONFIRM_THRESHOLD:
            print(f"Confirming schedule {schedule['id']}: {nicknames} -> {best_date.isoformat()} ({best_count} reactions)")
            voice_channel_id = None
            if not dry_run:
                try:
                    voice_channel_id = create_voice_channel(
                        guild_id, f"ゆるマッチング_{best_date.month}{best_date.day:02d}", list(group_user_ids), bot_token,
                    )
                except RuntimeError as exc:
                    # Missing "Manage Channels" permission for the bot role, most likely --
                    # a Discord server setting only an admin can grant, not something this
                    # script can fix. Still confirm the date; just skip the voice channel.
                    print(f"  voice channel creation failed, confirming date only: {exc}")

                date_line = (
                    f"🎉 開催決定！{best_date.month}/{best_date.day}({matching.WEEKDAY_KANJI[best_date.weekday()]}) "
                    f"{best_date.hour:02d}:{best_date.minute:02d}〜"
                )
                confirmation = (
                    f"{date_line}\n当日はこちらの専用通話部屋からどうぞ🔒🎙️（終了後に自動で消えます）"
                    if voice_channel_id else date_line
                )
                matching.discord_post(channel_id, bot_token, confirmation)
                requests_patch(
                    supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                    {
                        "status": "confirmed",
                        "confirmed_date": best_date.isoformat(),
                        "confirmed_reaction_count": best_count,
                        "voice_channel_id": voice_channel_id,
                    },
                )
        elif proposed_dates[-1] < now:
            print(f"Expiring schedule {schedule['id']}: {nicknames} (no option reached {matching.SCHEDULE_CONFIRM_THRESHOLD})")
            if not dry_run:
                requests_patch(
                    supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                    {"status": "expired"},
                )
        else:
            print(f"Schedule {schedule['id']} still open: {nicknames} (best so far: {best_count})")


def cleanup_voice_channels(supabase_url: str, service_role_key: str, bot_token: str, now: datetime, dry_run: bool) -> None:
    headers_select = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    req = Request(
        f"{supabase_url}/rest/v1/member_match_schedules"
        "?select=id,confirmed_date,voice_channel_id&status=eq.confirmed&voice_channel_id=not.is.null&voice_channel_deleted_at=is.null",
        headers=headers_select, method="GET",
    )
    with urlopen(req, timeout=30) as res:
        schedules = json.loads(res.read().decode("utf-8"))

    cutoff = now - timedelta(hours=VOICE_CHANNEL_CLEANUP_BUFFER_HOURS)
    for schedule in schedules:
        confirmed_date = datetime.fromisoformat(schedule["confirmed_date"])
        if confirmed_date > cutoff:
            continue
        print(f"Deleting voice channel for schedule {schedule['id']} (event was {confirmed_date.isoformat()})")
        if not dry_run:
            delete_channel(schedule["voice_channel_id"], bot_token)
            requests_patch(
                supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                {"voice_channel_deleted_at": now.isoformat()},
            )


def requests_patch(supabase_url: str, service_role_key: str, path: str, body: dict[str, Any]) -> None:
    req = Request(
        f"{supabase_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        method="PATCH",
    )
    with urlopen(req, timeout=30):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirm ゆるマッチング schedule proposals and manage temporary voice channels.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without posting/writing/creating anything.")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    bot_token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")
    channel_id = require_env("DISCORD_MATCHING_CHANNEL_ID")

    now = datetime.now(timezone.utc)

    confirm_schedules(supabase_url, service_role_key, channel_id, guild_id, bot_token, now, args.dry_run)
    cleanup_voice_channels(supabase_url, service_role_key, bot_token, now, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
