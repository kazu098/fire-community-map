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
import re
import time
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
THREAD_CONFIRM_EMOJI = "✅"
THREAD_LOOKBACK_LIMIT = 200

POSITIVE_DATE_RE = re.compile(r"(?:OK|ok|いけ|行け|大丈夫|空いて|あいて|できます|参加|可能|可|よい|良い)")
NEGATIVE_DATE_RE = re.compile(r"(?:NG|ng|無理|厳し|だめ|ダメ|不可|行けない|いけない|難し)")
DATE_RE = re.compile(r"(?:(20\d{2})\s*[年/.-]\s*)?(\d{1,2})\s*(?:月|/|-)\s*(\d{1,2})\s*日?")
DAY_ONLY_RE = re.compile(r"(?<![月/\-\d])(\d{1,2})\s*日")


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
    while True:
        try:
            with urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = 1.0
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                    retry_after = float(payload.get("retry_after", retry_after))
                except Exception:
                    pass
                time.sleep(retry_after)
                continue
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


def fetch_bot_user_id(token: str) -> str:
    return str(discord_get(f"{DISCORD_API_BASE}/users/@me", token)["id"])


def fetch_message_thread_id(channel_id: str, message_id: str, token: str) -> str | None:
    message = discord_get(f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}", token)
    thread = message.get("thread")
    if isinstance(thread, dict) and thread.get("id"):
        return str(thread["id"])
    return None


def fetch_channel_messages(channel_id: str, token: str, limit: int = THREAD_LOOKBACK_LIMIT) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    before: str | None = None
    while len(messages) < limit:
        page_limit = min(100, limit - len(messages))
        suffix = f"?limit={page_limit}"
        if before:
            suffix += f"&before={before}"
        page = discord_get(f"{DISCORD_API_BASE}/channels/{channel_id}/messages{suffix}", token)
        if not page:
            break
        messages.extend(page)
        before = str(page[-1]["id"])
        if len(page) < page_limit:
            break
    return messages


def create_voice_channel(guild_id: str, name: str, member_user_ids: list[str], bot_user_id: str, token: str) -> str:
    # @everyoneをdenyしただけだと、Bot自身もそのroleでしか判定されず自分のチャンネルを
    # 見られなくなる(サーバーイベントの紐付けや、期限後の自動削除がMissing Accessで
    # 失敗する)。Botのuser idにも明示的にallowのoverwriteを付けて、自分自身は常に
    # 見える/操作できるようにしておく。
    overwrites = [
        {"id": guild_id, "type": 0, "allow": "0", "deny": str(VOICE_CHANNEL_PERMISSION_BITS)},
        {"id": bot_user_id, "type": 1, "allow": str(VOICE_CHANNEL_PERMISSION_BITS), "deny": "0"},
    ]
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


def create_scheduled_event(
    guild_id: str, channel_id: str, name: str, description: str, start: datetime, token: str,
) -> str:
    """Discordのサーバーイベント(予定されたイベント)を、開催決定した専用ボイスチャンネルに
    紐づけて作成する。誰でも一覧に名前は見えるが、実際にそのボイスチャンネルへ入れるのは
    permission_overwritesで許可された対象メンバーだけ(create_voice_channel参照)。"""
    body = {
        "name": name,
        "description": description,
        "privacy_level": 2,  # GUILD_ONLY (Discordで選べる唯一の値)
        "scheduled_start_time": start.isoformat(),
        "scheduled_end_time": (start + timedelta(hours=2)).isoformat(),
        "entity_type": 2,  # VOICE
        "channel_id": channel_id,
    }
    req = Request(
        f"{DISCORD_API_BASE}/guilds/{guild_id}/scheduled-events",
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
        raise RuntimeError(f"Discord API error {exc.code} creating scheduled event: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed creating scheduled event: {exc}") from exc


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


def date_candidates_from_text(text: str, base_time: datetime, now: datetime) -> list[tuple[datetime, str]]:
    now_jst = now.astimezone(matching.JST)
    candidates: list[tuple[datetime, str]] = []
    for match in DATE_RE.finditer(text):
        year = int(match.group(1)) if match.group(1) else now_jst.year
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            date = base_time.replace(year=year, month=month, day=day)
        except ValueError:
            continue
        if not match.group(1) and date < now_jst - timedelta(days=1):
            try:
                date = date.replace(year=year + 1)
            except ValueError:
                continue
        start = match.start()
        end = min(len(text), match.end() + 32)
        candidates.append((date, text[start:end]))
    return candidates


def thread_date_votes(
    messages: list[dict[str, Any]],
    group_user_ids: set[str],
    proposed_dates: list[datetime],
    now: datetime,
) -> dict[datetime, set[str]]:
    if not proposed_dates:
        return {}
    proposed_keys = {d.date() for d in proposed_dates}
    base_time = proposed_dates[0]
    explicit_dates: set[datetime] = set()
    for message in messages:
        content = str(message.get("content") or "")
        for date, _context in date_candidates_from_text(content, base_time, now):
            if date.date() not in proposed_keys:
                explicit_dates.add(date)

    user_votes: dict[str, set[datetime]] = {}
    for message in sorted(messages, key=lambda item: item.get("timestamp", "")):
        author = message.get("author") or {}
        user_id = str(author.get("id") or "")
        if user_id not in group_user_ids:
            continue
        content = str(message.get("content") or "")
        candidates = date_candidates_from_text(content, base_time, now)
        for match in DAY_ONLY_RE.finditer(content):
            day = int(match.group(1))
            matching_explicit_dates = [date for date in explicit_dates if date.day == day]
            if len(matching_explicit_dates) != 1:
                continue
            start = match.start()
            end = min(len(content), match.end() + 32)
            candidates.append((matching_explicit_dates[0], content[start:end]))
        for date, context in candidates:
            if date.date() in proposed_keys:
                continue
            votes = user_votes.setdefault(user_id, set())
            if NEGATIVE_DATE_RE.search(context):
                votes.discard(date)
            elif POSITIVE_DATE_RE.search(context):
                votes.add(date)

    by_date: dict[datetime, set[str]] = {}
    for user_id, dates in user_votes.items():
        for date in dates:
            by_date.setdefault(date, set()).add(user_id)
    return by_date


def format_thread_confirmation_prompt(date: datetime, count: int) -> str:
    return (
        f"🐾 スレッドを見ると、{date.month}/{date.day}({matching.WEEKDAY_KANJI[date.weekday()]}) "
        f"{date.hour:02d}:{date.minute:02d}〜 なら集まれそうです（いま{count}人が前向きそう）。\n"
        f"この日で決定する場合は {THREAD_CONFIRM_EMOJI} を押してください。"
    )


def confirm_schedule_date(
    supabase_url: str,
    service_role_key: str,
    schedule_id: str,
    guild_id: str,
    post_channel_id: str,
    bot_token: str,
    bot_user_id: str,
    nicknames: list[str],
    confirmed_user_ids: set[str],
    date: datetime,
    reaction_count: int,
    source: str,
    dry_run: bool,
) -> None:
    print(f"Confirming schedule {schedule_id}: {nicknames} -> {date.isoformat()} ({reaction_count} via {source})")
    voice_channel_id = None
    if not dry_run:
        try:
            voice_channel_id = create_voice_channel(
                guild_id, f"ゆるマッチング_{date.month}{date.day:02d}", list(confirmed_user_ids), bot_user_id, bot_token,
            )
        except RuntimeError as exc:
            print(f"  voice channel creation failed, confirming date only: {exc}")

        if voice_channel_id:
            try:
                create_scheduled_event(
                    guild_id, voice_channel_id,
                    f"ゆるマッチング {date.month}/{date.day}({matching.WEEKDAY_KANJI[date.weekday()]})",
                    f"{'、'.join(nicknames)}さんのゆるマッチング",
                    date, bot_token,
                )
            except RuntimeError as exc:
                print(f"  scheduled event creation failed: {exc}")

        mention_prefix = " ".join(f"<@{user_id}>" for user_id in sorted(confirmed_user_ids))
        date_line = (
            f"{mention_prefix}\n🎉 開催決定！{date.month}/{date.day}({matching.WEEKDAY_KANJI[date.weekday()]}) "
            f"{date.hour:02d}:{date.minute:02d}〜"
        )
        confirmation = (
            f"{date_line}\n当日はこちらの専用通話部屋（<#{voice_channel_id}>）からどうぞ🔒🎙️（終了後に自動で消えます）"
            if voice_channel_id else date_line
        )
        matching.discord_post(post_channel_id, bot_token, confirmation, list(confirmed_user_ids))
        patch_body: dict[str, Any] = {
            "status": "confirmed",
            "confirmed_date": date.isoformat(),
            "confirmed_reaction_count": reaction_count,
            "confirmed_source": source,
            "voice_channel_id": voice_channel_id,
        }
        if source == "thread_confirmation":
            patch_body["thread_confirmation_reaction_count"] = reaction_count
        requests_patch(
            supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule_id}",
            patch_body,
        )


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

    schedules = get(
        "/rest/v1/member_match_schedules"
        "?select=id,group_id,proposed_dates,discord_message_id,thread_id,thread_confirmation_message_id,thread_confirmation_date"
        "&status=eq.proposed"
    )
    if not schedules:
        print("No proposed schedules to check.")
        return

    guild_display_name_ids = matching.fetch_guild_member_ids_by_display_name(bot_token, guild_id)
    name_overrides = matching.load_discord_name_overrides(Path("config/member_discord_name_map.csv"))
    bot_user_id = fetch_bot_user_id(bot_token)

    for schedule in schedules:
        group_id = schedule["group_id"]
        members = get(f"/rest/v1/member_match_group_members?group_id=eq.{group_id}&select=member_nickname")
        nicknames = [m["member_nickname"] for m in members]
        discord_user_ids = matching.resolve_discord_user_ids(nicknames, guild_display_name_ids, name_overrides)
        group_user_ids = set(discord_user_ids.values())

        # Supabase/PostgREST always returns timestamptz as UTC; convert back to JST so the
        # displayed date/time (confirmation message, voice channel name) matches what was
        # originally proposed (next_occurrences works in JST) rather than showing UTC clock
        # values like "01:00" for what was proposed as "10:00".
        proposed_dates = [datetime.fromisoformat(d).astimezone(matching.JST) for d in schedule["proposed_dates"]]
        message_id = schedule["discord_message_id"]

        thread_id = schedule.get("thread_id")
        if message_id:
            try:
                thread_id = thread_id or fetch_message_thread_id(channel_id, message_id, bot_token)
            except RuntimeError as exc:
                print(f"  could not fetch schedule message thread for {schedule['id']}: {exc}")
        if not thread_id:
            group_rows = get(f"/rest/v1/member_match_groups?id=eq.{group_id}&select=discord_message_id")
            group_message_id = group_rows[0].get("discord_message_id") if group_rows else None
            if group_message_id:
                try:
                    thread_id = fetch_message_thread_id(channel_id, group_message_id, bot_token)
                except RuntimeError as exc:
                    print(f"  could not fetch match message thread for {schedule['id']}: {exc}")

        nickname_by_user_id = {v: k for k, v in discord_user_ids.items()}

        date_reactors: dict[datetime, set[str]] = {}
        counts: list[tuple[datetime, int]] = []
        for date, emoji in zip(proposed_dates, matching.DATE_OPTION_EMOJI):
            reactors = fetch_reactors(channel_id, message_id, emoji, bot_token) & group_user_ids
            date_reactors[date] = reactors
            counts.append((date, len(reactors)))

        best_date, best_count = max(counts, key=lambda item: (item[1], -item[0].timestamp()))

        if best_count >= matching.SCHEDULE_CONFIRM_THRESHOLD:
            confirmed_user_ids = date_reactors[best_date]
            confirmed_nicknames = [nickname_by_user_id[uid] for uid in confirmed_user_ids if uid in nickname_by_user_id]
            confirm_schedule_date(
                supabase_url, service_role_key, schedule["id"], guild_id, channel_id, bot_token,
                bot_user_id, confirmed_nicknames, confirmed_user_ids, best_date, best_count, "reaction_poll", dry_run,
            )
            continue

        thread_confirmation_message_id = schedule.get("thread_confirmation_message_id")
        if thread_confirmation_message_id and thread_id:
            thread_confirmation_date = datetime.fromisoformat(schedule["thread_confirmation_date"]).astimezone(matching.JST)
            reactors = fetch_reactors(thread_id, thread_confirmation_message_id, THREAD_CONFIRM_EMOJI, bot_token) & group_user_ids
            confirm_count = len(reactors)
            if confirm_count >= matching.SCHEDULE_CONFIRM_THRESHOLD:
                confirmed_nicknames = [nickname_by_user_id[uid] for uid in reactors if uid in nickname_by_user_id]
                confirm_schedule_date(
                    supabase_url, service_role_key, schedule["id"], guild_id, thread_id, bot_token,
                    bot_user_id, confirmed_nicknames, reactors, thread_confirmation_date, confirm_count,
                    "thread_confirmation", dry_run,
                )
                continue
            if not dry_run:
                requests_patch(
                    supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                    {"thread_confirmation_reaction_count": confirm_count},
                )
            print(f"Schedule {schedule['id']} thread confirmation still open: {nicknames} (best so far: {confirm_count})")
            if thread_confirmation_date < now:
                print(f"Expiring schedule {schedule['id']}: {nicknames} (thread confirmation date has passed)")
                if not dry_run:
                    requests_patch(
                        supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                        {"status": "expired"},
                    )
        elif thread_id:
            messages = fetch_channel_messages(thread_id, bot_token)
            thread_votes = thread_date_votes(messages, group_user_ids, proposed_dates, now)
            if thread_votes:
                thread_best_date, voters = max(thread_votes.items(), key=lambda item: (len(item[1]), -item[0].timestamp()))
                if len(voters) >= matching.SCHEDULE_CONFIRM_THRESHOLD:
                    print(
                        f"Posting thread confirmation for schedule {schedule['id']}: "
                        f"{nicknames} -> {thread_best_date.isoformat()} ({len(voters)} text votes)"
                    )
                    if not dry_run:
                        prompt = format_thread_confirmation_prompt(thread_best_date, len(voters))
                        confirmation_message_id = matching.discord_post(thread_id, bot_token, prompt)
                        if confirmation_message_id:
                            matching.discord_add_reaction(thread_id, confirmation_message_id, bot_token, THREAD_CONFIRM_EMOJI)
                            requests_patch(
                                supabase_url, service_role_key,
                                f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                                {
                                    "thread_id": thread_id,
                                    "thread_suggested_date": thread_best_date.isoformat(),
                                    "thread_confirmation_message_id": confirmation_message_id,
                                    "thread_confirmation_date": thread_best_date.isoformat(),
                                    "thread_confirmation_reaction_count": 0,
                                },
                            )
                    continue
            latest_open_date = max([*proposed_dates, *thread_votes.keys()])
            if latest_open_date < now:
                print(f"Expiring schedule {schedule['id']}: {nicknames} (no option reached {matching.SCHEDULE_CONFIRM_THRESHOLD})")
                if not dry_run:
                    requests_patch(
                        supabase_url, service_role_key, f"/rest/v1/member_match_schedules?id=eq.{schedule['id']}",
                        {"status": "expired"},
                    )
            else:
                print(f"Schedule {schedule['id']} still open: {nicknames} (best so far: {best_count})")
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
            try:
                delete_channel(schedule["voice_channel_id"], bot_token)
            except RuntimeError as exc:
                # Don't let one channel's cleanup failure (e.g. permissions) crash the
                # whole run and block cleanup of every other schedule after it.
                print(f"  voice channel deletion failed, leaving it for next time: {exc}")
                continue
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
