#!/usr/bin/env python3
"""Count hands on 相談テーママッチング posts and turn them into ゆるマッチング groups (issue #322).

A member posts a consultation theme from the map; the consultation-request Edge Function has
ふぁいにゃ post it anonymously to the ゆるマッチング channel with a ✋ reaction. This batch, run
with the regular matching (3 times a day), checks every `recruiting` theme:

- Post deleted (an admin removed an inappropriate one) -> the theme is withdrawn.
- ✋ from a member who is not opted in to ゆるマッチング, or has no availability -> DM once,
  asking them to turn it on and register their free time (they can't be scheduled otherwise).
- Hands from opted-in members are taken first-come (first time this batch saw the reaction;
  Discord doesn't expose reaction times), each kept only if the group still shares at least
  one weekly slot with them -- starting from the consultant's own availability.
- 3 hands (4 people with the consultant) -> matched right away. After 3 days, 2 hands (3
  people) -> matched. The group then goes through the regular date poll -> confirmation ->
  voice channel -> reminder -> survey flow (process_member_match_schedules.py).
- 7 days without a group -> expired, and the consultant gets a DM.

The consultant's name is shown only once the group is formed (the match announcement), the
same as regular ゆるマッチング. --dry-run prints what would happen without writing anything.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import process_member_match_schedules as schedules
import run_member_matching as matching

HAND_EMOJI = "✋"
GROUP_TARGET_HANDS = 3  # + the consultant = 4, the ideal size
GROUP_MIN_HANDS = 2  # + the consultant = 3
MIN_HANDS_AFTER = timedelta(days=3)


def supabase(supabase_url: str, key: str, method: str, path: str, body: Any = None) -> Any:
    req = Request(
        f"{supabase_url}/rest/v1/{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        method=method,
    )
    with urlopen(req, timeout=30) as res:
        raw = res.read().decode("utf-8")
        return json.loads(raw) if raw else None


def fetch_message(channel_id: str, message_id: str, token: str) -> dict[str, Any] | None:
    try:
        return schedules.discord_get(f"{schedules.DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}", token)
    except RuntimeError as exc:
        if "error 404" in str(exc):
            return None
        raise


def send_dm(user_id: str, content: str, token: str) -> None:
    """DM one member. A member whose DMs are closed (Discord 50007) is skipped quietly."""
    def post(path: str, payload: dict[str, Any]) -> Any:
        req = Request(
            f"{schedules.DISCORD_API_BASE}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bot {token}",
                "User-Agent": schedules.USER_AGENT,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8") or "null")

    try:
        channel = post("/users/@me/channels", {"recipient_id": user_id})
        post(f"/channels/{channel['id']}/messages", {"content": content, "allowed_mentions": {"parse": []}})
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        if '"code": 50007' in body_text or '"code":50007' in body_text:
            return
        raise RuntimeError(f"Discord API error {exc.code} sending DM: {body_text}") from exc


def edit_message(channel_id: str, message_id: str, content: str, token: str) -> None:
    req = Request(
        f"{schedules.DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": schedules.USER_AGENT,
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    with urlopen(req, timeout=30):
        pass


def pick_group(
    consultant_slots: set[tuple[str, int]],
    responders: list[dict[str, Any]],
    slots_by_nickname: dict[str, set[tuple[str, int]]],
) -> tuple[list[str], set[tuple[str, int]]]:
    """First-come hands that keep a common weekly slot with everyone picked so far."""
    common = set(consultant_slots)
    picked: list[str] = []
    for responder in responders:
        nickname = responder["nickname"]
        shared = common & slots_by_nickname.get(nickname, set())
        if not shared:
            continue
        picked.append(nickname)
        common = shared
        if len(picked) == GROUP_TARGET_HANDS:
            break
    return picked, common


def should_match(hand_count: int, posted_at: datetime, now: datetime) -> bool:
    if hand_count >= GROUP_TARGET_HANDS:
        return True
    return hand_count >= GROUP_MIN_HANDS and now - posted_at >= MIN_HANDS_AFTER


def soonest_slot(common: set[tuple[str, int]], now: datetime) -> tuple[str, int]:
    return min(common, key=lambda slot: matching.next_occurrences(slot[0], slot[1], now, count=1)[0])


def merge_responders(previous: list[dict[str, Any]], current_nicknames: set[str], now: datetime) -> list[dict[str, Any]]:
    """Keep first_seen_at for hands still raised, drop withdrawn ones, append new ones."""
    kept = [r for r in previous if r["nickname"] in current_nicknames]
    known = {r["nickname"] for r in kept}
    added = [{"nickname": n, "first_seen_at": now.isoformat()} for n in sorted(current_nicknames - known)]
    return kept + added


def closed_post(body: str, note: str) -> str:
    quoted = "\n".join(f"> {line}" for line in body.split("\n"))
    return f"🐾 ふぁいにゃです。こんな相談テーマで話したい人がいました。\n{quoted}\n\n{note}"


def format_optin_dm(site_url: str) -> str:
    return "\n".join([
        "🐾 ふぁいにゃです。相談テーマの募集に手を挙げてくれてありがとうございます！",
        "日程を合わせるため、コミュニティマップの自分のプロフィールで「ゆるマッチング」をONにして、空いている時間帯を登録してください。",
        "登録しないと日程を決められないので、手を挙げた人として数えられません（登録したあとに付けたままの ✋ は、次の確認から数えます）。",
        site_url,
    ])


def format_expired_dm(body: str) -> str:
    first_line = body.split("\n")[0]
    if len(first_line) > 40:
        first_line = first_line[:40] + "…"
    return "\n".join([
        "🐾 ふぁいにゃです。相談テーマの募集についてのお知らせです。",
        f"「{first_line}」は、1週間のうちに時間帯が合う方が集まらなかったので、募集を終了しました。",
        "時間帯を広げたり、書き方を変えたりして、またいつでも募集してみてください。",
    ])


def format_match_announcement(body: str, nicknames: list[str], user_ids: dict[str, str], slot: tuple[str, int]) -> str:
    first_line = body.split("\n")[0]
    if len(first_line) > 60:
        first_line = first_line[:60] + "…"
    names = "、".join(f"<@{user_ids[n]}>" if n in user_ids else f"**{n}** さん" for n in nicknames)
    day = matching.DAY_LABELS.get(slot[0], slot[0])
    return "\n".join([
        f"🐾 相談テーマ「{first_line}」で、{names}がマッチしたにゃ♪",
        f"最初の {names.split('、')[0]} が相談テーマを書いてくれた方です。みんな「{day}曜{slot[1]}時」が空いているみたい",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Count hands on 相談テーママッチング posts and form groups.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    schedules.load_dotenv(Path(args.env_file))
    supabase_url = schedules.require_env("SUPABASE_URL")
    key = schedules.require_env("SUPABASE_SERVICE_ROLE_KEY")
    bot_token = schedules.require_env("DISCORD_BOT_TOKEN")
    channel_id = schedules.require_env("DISCORD_MATCHING_CHANNEL_ID")
    site_url = os.environ.get("SITE_BASE_URL", matching.SITE_BASE_URL)
    now = datetime.now(timezone.utc)

    requests = supabase(
        supabase_url, key, "GET",
        "consultation_requests?select=id,member_nickname,body,discord_message_id,posted_at,deadline_at,responders,optin_notified_user_ids"
        "&status=eq.recruiting&order=posted_at",
    )
    if not requests:
        print("No recruiting consultation themes.")
        return 0

    profiles = supabase(supabase_url, key, "GET", "member_profiles?select=nickname,discord_user_id&discord_user_id=not.is.null")
    nickname_by_user_id = {str(p["discord_user_id"]): p["nickname"] for p in profiles}
    user_id_by_nickname = {nickname: user_id for user_id, nickname in nickname_by_user_id.items()}
    settings = supabase(supabase_url, key, "GET", "member_matching_settings?select=member_nickname,opted_in")
    opted_in = {s["member_nickname"] for s in settings if s.get("opted_in")}
    availability = matching.build_slot_index(
        supabase(supabase_url, key, "GET", "member_availability?select=member_nickname,day_of_week,hour")
    )
    bot_user_id = schedules.fetch_bot_user_id(bot_token)

    for request in requests:
        request_id = request["id"]
        consultant = request["member_nickname"]
        body = request["body"]
        message_id = request.get("discord_message_id")
        posted_at = datetime.fromisoformat(request["posted_at"])
        deadline = datetime.fromisoformat(request["deadline_at"])

        def patch(fields: dict[str, Any]) -> None:
            if not args.dry_run:
                supabase(supabase_url, key, "PATCH", f"consultation_requests?id=eq.{request_id}", fields)

        if not message_id or fetch_message(channel_id, message_id, bot_token) is None:
            print(f"Theme {request_id}: post is gone -> withdrawn")
            patch({"status": "withdrawn", "closed_at": now.isoformat()})
            continue

        reactor_ids = schedules.fetch_reactors(channel_id, message_id, HAND_EMOJI, bot_token)
        reactor_ids -= {bot_user_id, user_id_by_nickname.get(consultant, "")}

        notified = set(request.get("optin_notified_user_ids") or [])
        countable: set[str] = set()
        for user_id in sorted(reactor_ids):
            nickname = nickname_by_user_id.get(user_id)
            if not nickname or nickname == consultant:
                continue
            if nickname in opted_in and availability.get(nickname):
                countable.add(nickname)
            elif user_id not in notified:
                print(f"Theme {request_id}: {nickname} raised a hand but is not opted in / has no availability -> DM")
                if not args.dry_run:
                    try:
                        send_dm(user_id, format_optin_dm(site_url), bot_token)
                    except RuntimeError as exc:
                        print(f"  DM failed: {exc}")
                notified.add(user_id)

        responders = merge_responders(request.get("responders") or [], countable, now)
        picked, common = pick_group(availability.get(consultant, set()), responders, availability)
        print(f"Theme {request_id}: {len(reactor_ids)} hands, {len(picked)} counted {picked}")

        if picked and should_match(len(picked), posted_at, now):
            slot = soonest_slot(common, now)
            members = [consultant, *picked]
            print(f"Theme {request_id}: matched {members} at {slot}")
            if not args.dry_run:
                group_id = str(uuid.uuid4())
                user_ids = {n: user_id_by_nickname[n] for n in members if n in user_id_by_nickname}
                announcement_id = matching.discord_post(
                    channel_id, bot_token, format_match_announcement(body, members, user_ids, slot), list(user_ids.values()),
                )
                supabase(supabase_url, key, "POST", "member_match_groups", [{
                    "id": group_id, "day_of_week": slot[0], "hour": slot[1],
                    "discord_message_id": announcement_id, "posted_at": now.isoformat(),
                }])
                supabase(supabase_url, key, "POST", "member_match_group_members",
                         [{"group_id": group_id, "member_nickname": n} for n in members])
                dates = matching.next_occurrences(slot[0], slot[1], now)
                schedule_message_id = matching.discord_post(
                    channel_id, bot_token, matching.format_schedule_proposal(slot[0], slot[1], dates),
                )
                for emoji in matching.DATE_OPTION_EMOJI[: len(dates)]:
                    matching.discord_add_reaction(channel_id, schedule_message_id, bot_token, emoji)
                supabase(supabase_url, key, "POST", "member_match_schedules", [{
                    "group_id": group_id,
                    "proposed_dates": [d.isoformat() for d in dates],
                    "discord_message_id": schedule_message_id,
                }])
                edit_message(channel_id, message_id, closed_post(body, "✅ 話せる方が集まったので、募集を締め切りました。ありがとうございました！"), bot_token)
                patch({
                    "status": "matched", "group_id": group_id, "closed_at": now.isoformat(),
                    "responders": responders, "responder_count": len(picked),
                    "optin_notified_user_ids": sorted(notified),
                })
            continue

        if now >= deadline:
            print(f"Theme {request_id}: deadline passed -> expired")
            if not args.dry_run:
                edit_message(channel_id, message_id, closed_post(body, "⏰ 締め切りになったので、募集を終了しました。"), bot_token)
                consultant_id = user_id_by_nickname.get(consultant)
                if consultant_id:
                    try:
                        send_dm(consultant_id, format_expired_dm(body), bot_token)
                    except RuntimeError as exc:
                        print(f"  DM failed: {exc}")
            patch({
                "status": "expired", "closed_at": now.isoformat(),
                "responders": responders, "responder_count": len(picked),
                "optin_notified_user_ids": sorted(notified),
            })
            continue

        patch({"responders": responders, "responder_count": len(picked), "optin_notified_user_ids": sorted(notified)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
