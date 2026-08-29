#!/usr/bin/env python3
"""Availability-based random matching batch (プチおせっかい機能).

Pairs up opted-in members whose availability (weekday x time-of-day slot)
overlaps, at random -- no tag/embedding similarity involved. See GitHub
issue #76 for the design background.

For each member whose matching interval has elapsed (member_matching_settings
.last_matched_at + interval_days <= today, or never matched):
  1. Collect their registered availability slots (member_availability).
  2. Randomly pair eligible members who share at least one slot, skipping
     pairs matched within the cooldown window (member_matches).
  3. Record the match in member_matches and bump last_matched_at for both
     members.
  4. Post an announcement to the Discord matching channel, if configured.

The dedicated Discord matching channel does not exist yet (pending
agreement), so --post-to-discord is opt-in and the script no-ops the
Discord step -- logging what it would have posted -- when
DISCORD_MATCHING_CHANNEL_ID is unset. Run with --dry-run to preview matches
without writing to Supabase or posting to Discord.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-member-matching/0.1"
COOLDOWN_DAYS = 60  # avoid re-matching the same pair within this window

DAY_LABELS = {
    "mon": "月", "tue": "火", "wed": "水", "thu": "木",
    "fri": "金", "sat": "土", "sun": "日",
}
SLOT_LABELS = {"morning": "午前", "afternoon": "午後", "evening": "夜"}


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


def supabase_request(
    method: str,
    url: str,
    service_role_key: str,
    body: Any = None,
    prefer: str | None = None,
) -> Any:
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


def discord_post(channel_id: str, token: str, content: str) -> str | None:
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode("utf-8"),
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
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} posting to channel {channel_id}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed posting to channel {channel_id}: {exc}") from exc


def is_due(setting: dict[str, Any], now: datetime) -> bool:
    last_matched_at = setting.get("last_matched_at")
    if not last_matched_at:
        return True
    last = datetime.fromisoformat(last_matched_at.replace("Z", "+00:00"))
    interval_days = setting.get("interval_days") or 7
    return now - last >= timedelta(days=interval_days)


def build_slot_index(availability: list[dict[str, Any]]) -> dict[str, set[tuple[str, str]]]:
    """member_nickname -> set of (day_of_week, time_slot)."""
    index: dict[str, set[tuple[str, str]]] = {}
    for row in availability:
        index.setdefault(row["member_nickname"], set()).add((row["day_of_week"], row["time_slot"]))
    return index


def recent_pairs(matches: list[dict[str, Any]], now: datetime) -> set[frozenset[str]]:
    cutoff = now - timedelta(days=COOLDOWN_DAYS)
    pairs = set()
    for m in matches:
        created_at = datetime.fromisoformat(m["created_at"].replace("Z", "+00:00"))
        if created_at >= cutoff:
            pairs.add(frozenset((m["member_a"], m["member_b"])))
    return pairs


def run_matching(
    eligible_nicknames: list[str],
    slot_index: dict[str, set[tuple[str, str]]],
    excluded_pairs: set[frozenset[str]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Randomly pair eligible members who share an availability slot."""
    pool = [n for n in eligible_nicknames if slot_index.get(n)]
    rng.shuffle(pool)
    matched: set[str] = set()
    results: list[dict[str, Any]] = []

    for nickname in pool:
        if nickname in matched:
            continue
        candidates = [
            other for other in pool
            if other != nickname
            and other not in matched
            and frozenset((nickname, other)) not in excluded_pairs
            and slot_index[nickname] & slot_index[other]
        ]
        if not candidates:
            continue
        partner = rng.choice(candidates)
        shared = sorted(slot_index[nickname] & slot_index[partner])
        day_of_week, time_slot = rng.choice(shared)
        results.append({
            "member_a": nickname,
            "member_b": partner,
            "day_of_week": day_of_week,
            "time_slot": time_slot,
        })
        matched.add(nickname)
        matched.add(partner)

    return results


def format_announcement(match: dict[str, Any]) -> str:
    day = DAY_LABELS.get(match["day_of_week"], match["day_of_week"])
    slot = SLOT_LABELS.get(match["time_slot"], match["time_slot"])
    return (
        f"🎲 **{match['member_a']}** さんと **{match['member_b']}** さんがマッチングしました！\n"
        f"お二人とも「{day}曜{slot}」が空いているようなので、よければ気が向いたタイミングで声をかけてみてください。"
        "（開催するかどうかはお二人にお任せします）"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the availability-based random matching batch.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="Compute matches without writing to Supabase or posting to Discord.")
    parser.add_argument("--post-to-discord", action="store_true", help="Post match announcements to DISCORD_MATCHING_CHANNEL_ID. No-op with a warning if that env var is unset.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed, for reproducible dry runs.")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc)

    headers_select = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}

    def get(path: str) -> Any:
        req = Request(f"{supabase_url}{path}", headers=headers_select, method="GET")
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))

    settings = get("/rest/v1/member_matching_settings?select=member_nickname,opted_in,interval_days,last_matched_at&opted_in=eq.true")
    availability = get("/rest/v1/member_availability?select=member_nickname,day_of_week,time_slot")
    recent_matches = get(
        f"/rest/v1/member_matches?select=member_a,member_b,created_at&created_at=gte.{(now - timedelta(days=COOLDOWN_DAYS)).isoformat()}"
    )

    due_nicknames = [s["member_nickname"] for s in settings if is_due(s, now)]
    slot_index = build_slot_index(availability)
    excluded_pairs = recent_pairs(recent_matches, now)

    matches = run_matching(due_nicknames, slot_index, excluded_pairs, rng)

    print(f"Opted-in & due: {len(due_nicknames)} / matched this run: {len(matches)}")
    for match in matches:
        print(f"  {match['member_a']} <-> {match['member_b']}  ({DAY_LABELS[match['day_of_week']]}曜{SLOT_LABELS[match['time_slot']]})")

    if args.dry_run:
        print("--dry-run: no writes to Supabase, no Discord post.")
        return 0

    if not matches:
        return 0

    channel_id = os.environ.get("DISCORD_MATCHING_CHANNEL_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")

    for match in matches:
        message_id = None
        posted_at = None
        if args.post_to_discord:
            if channel_id and bot_token:
                message_id = discord_post(channel_id, bot_token, format_announcement(match))
                posted_at = datetime.now(timezone.utc).isoformat()
            else:
                print(
                    "DISCORD_MATCHING_CHANNEL_ID is not set yet (channel not created). "
                    "Skipping Discord post; the match is still recorded.",
                )

        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/member_matches",
            service_role_key,
            body=[{
                "member_a": match["member_a"],
                "member_b": match["member_b"],
                "day_of_week": match["day_of_week"],
                "time_slot": match["time_slot"],
                "discord_message_id": message_id,
                "posted_at": posted_at,
            }],
            prefer="return=minimal",
        )

        for nickname in (match["member_a"], match["member_b"]):
            supabase_request(
                "PATCH",
                f"{supabase_url}/rest/v1/member_matching_settings?member_nickname=eq.{nickname}",
                service_role_key,
                body={"last_matched_at": now.isoformat()},
                prefer="return=minimal",
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
