#!/usr/bin/env python3
"""Availability-based random matching batch (ゆるマッチング).

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

The announcement is written in the voice of the community mascot ふぁいにゃ
(see docs/fainya-persona.md) and includes a conversation-starter suggestion
derived from the pair's shared tags (member_tags) and self-introductions
(member_profiles.self_intro_text), so the match feels less like a cold
random pairing.

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
from urllib.parse import quote
from urllib.request import Request, urlopen

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-member-matching/0.1"
COOLDOWN_DAYS = 60  # avoid re-matching the same pair within this window

DAY_LABELS = {
    "mon": "月", "tue": "火", "wed": "水", "thu": "木",
    "fri": "金", "sat": "土", "sun": "日",
}
SLOT_LABELS = {"morning": "午前", "afternoon": "午後", "evening": "夜"}

# Categories worth surfacing as a shared-interest conversation starter, in
# priority order. consultation/wants_to_know are handled separately (as a
# cross-match: one member's "相談できること" answering the other's
# "知りたいこと"), since that pairing is a stronger topic hint than a plain
# overlap.
TOPIC_TAG_CATEGORIES = ["interest", "investment_style", "affiliation", "skill", "mbti", "fire_status"]
TOPIC_CATEGORY_LABELS = {
    "interest": "興味",
    "investment_style": "投資スタイル",
    "affiliation": "活動・部活",
    "skill": "得意なこと",
    "mbti": "MBTI",
    "fire_status": "FIREタイプ",
}
# Free-text keywords to scan self_intro_text for, as a fallback when tags
# don't overlap. Deliberately broad/casual -- these surface a shared theme
# even when nobody bothered to tag it, at the cost of being a plain substring
# match rather than real language understanding.
INTRO_TOPIC_KEYWORDS = [
    "投資", "資産運用", "米国株", "インデックス投資", "高配当", "副業", "起業", "独立", "経営",
    "転職", "退職", "休職", "育休", "育児", "子育て", "妊活", "結婚", "移住", "多拠点生活", "海外",
    "旅行", "節約", "保険", "資格", "ブログ", "note", "YouTube", "執筆", "出版", "写真",
    "コミュニティ", "ボランティア", "筋トレ", "ランニング", "マラソン", "登山", "キャンプ", "ゴルフ",
    "読書", "ゲーム", "料理", "カフェ", "猫", "犬", "ペット", "音楽", "映画", "アニメ", "マンガ",
]


def _consultation_wants_cross_topic(members: list[dict[str, Any]]) -> str | None:
    """Any member's 相談できること matching another's 知りたいこと -- the strongest, most actionable hint."""
    for a in members:
        for b in members:
            if a is b:
                continue
            overlap = set(a["tags"].get("consultation", [])) & set(b["tags"].get("wants_to_know", []))
            if overlap:
                return f"「{sorted(overlap)[0]}」について、{a['nickname']}さんが{b['nickname']}さんの力になれそうにゃ"
    return None


def _shared_tag_topic(members: list[dict[str, Any]]) -> str | None:
    """A tag value every member in the group has in common, checked category by category."""
    for category in TOPIC_TAG_CATEGORIES:
        common: set[str] | None = None
        for m in members:
            values = set(m["tags"].get(category, []))
            common = values if common is None else common & values
        if common:
            label = TOPIC_CATEGORY_LABELS.get(category, category)
            return f"共通の{label}「{sorted(common)[0]}」の話で盛り上がれそうにゃ"
    return None


def _intro_keyword_topic(members: list[dict[str, Any]]) -> str | None:
    """A casual keyword every member's self-intro text mentions, even if nobody tagged it."""
    if not all(m.get("intro") for m in members):
        return None
    common: set[str] | None = None
    for m in members:
        matched = {kw for kw in INTRO_TOPIC_KEYWORDS if kw in m["intro"]}
        common = matched if common is None else common & matched
    if common:
        return f"自己紹介を読むと「{sorted(common)[0]}」が共通の話題になりそうにゃ"
    return None


def _note_writers_topic(members: list[dict[str, Any]]) -> str | None:
    """A light, low-stakes icebreaker: everyone in the group has a note link registered."""
    if all(any("note.com" in (link.get("url") or "") for link in m.get("links", [])) for m in members):
        return "みんなnoteをやっているみたいだから、記事を見せ合うのも面白そうにゃ"
    return None


def _same_prefecture_topic(members: list[dict[str, Any]]) -> str | None:
    prefectures = {m.get("prefecture") for m in members}
    if len(prefectures) == 1 and None not in prefectures:
        return f"実は{next(iter(prefectures))}在住どうし、というのも面白い共通点にゃ"
    return None


def _no_avatar_twins_topic(members: list[dict[str, Any]]) -> str | None:
    """Purely for a laugh: nobody in the group has set a profile photo yet."""
    if len(members) >= 2 and all(not m.get("has_avatar") for m in members):
        return "ちなみにお二人ともアイコン未設定どうし、というのもちょっとおもしろいにゃ"
    return None


# Evaluated in order; the first generator to return something wins. Roughly
# most-actionable -> most-lighthearted, so a real conversation hook beats a
# coincidence when both are available.
TOPIC_GENERATORS = [
    _consultation_wants_cross_topic,
    _shared_tag_topic,
    _intro_keyword_topic,
    _note_writers_topic,
    _same_prefecture_topic,
    _no_avatar_twins_topic,
]


def build_topic_suggestion(members: list[dict[str, Any]]) -> str | None:
    """Suggest a conversation topic for a matched group.

    Each member dict: {"nickname": str, "tags": dict[str, list[str]],
    "intro": str | None, "links": list[dict], "prefecture": str | None,
    "has_avatar": bool}. Tries actionable hints (consultation x wants_to_know,
    shared tags, shared self-intro keywords) before falling back to
    lighter/coincidental ones (both write on note, same prefecture, neither
    has set an avatar). Returns None if nothing at all stood out.
    """
    for generator in TOPIC_GENERATORS:
        topic = generator(members)
        if topic:
            return topic
    if all(m.get("intro") for m in members):
        return "お互いの自己紹介を読んでみると、意外な共通点が見つかるかもにゃ"
    return None


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


def format_announcement(match: dict[str, Any], topic: str | None) -> str:
    """Render the Discord announcement in ふぁいにゃ's voice (docs/fainya-persona.md)."""
    day = DAY_LABELS.get(match["day_of_week"], match["day_of_week"])
    slot = SLOT_LABELS.get(match["time_slot"], match["time_slot"])
    lines = [
        f"🐾 **{match['member_a']}** さん、**{match['member_b']}** さんがマッチしたにゃ！",
        f"お二人とも「{day}曜{slot}」が空いているみたいだから、🙏 よければ一度お話ししてみてほしいにゃ。"
        "（開催するかどうかはお二人にお任せするにゃ）",
    ]
    if topic:
        lines.append(f"\n💡 盛り上がりそうな話題: {topic}")
    return "\n".join(lines)


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
        f"/rest/v1/member_matches?select=member_a,member_b,created_at&created_at=gte.{quote((now - timedelta(days=COOLDOWN_DAYS)).isoformat())}"
    )
    member_tags = get("/rest/v1/member_tags?select=member_nickname,category,value")
    profiles = get("/rest/v1/member_profiles?select=nickname,self_intro_text,avatar_url")
    member_links = get("/rest/v1/member_links?select=member_nickname,label,url")
    member_locations = get("/rest/v1/member_locations?select=nickname,prefecture")

    due_nicknames = [s["member_nickname"] for s in settings if is_due(s, now)]
    slot_index = build_slot_index(availability)
    excluded_pairs = recent_pairs(recent_matches, now)

    tags_by_nickname: dict[str, dict[str, list[str]]] = {}
    for row in member_tags:
        tags_by_nickname.setdefault(row["member_nickname"], {}).setdefault(row["category"], []).append(row["value"])
    profile_by_nickname = {p["nickname"]: p for p in profiles}
    links_by_nickname: dict[str, list[dict[str, Any]]] = {}
    for row in member_links:
        links_by_nickname.setdefault(row["member_nickname"], []).append(row)
    prefecture_by_nickname = {loc["nickname"]: loc.get("prefecture") for loc in member_locations}

    def member_topic_input(nickname: str) -> dict[str, Any]:
        profile = profile_by_nickname.get(nickname, {})
        return {
            "nickname": nickname,
            "tags": tags_by_nickname.get(nickname, {}),
            "intro": profile.get("self_intro_text"),
            "links": links_by_nickname.get(nickname, []),
            "prefecture": prefecture_by_nickname.get(nickname),
            "has_avatar": bool(profile.get("avatar_url")),
        }

    matches = run_matching(due_nicknames, slot_index, excluded_pairs, rng)
    for match in matches:
        match["topic"] = build_topic_suggestion([
            member_topic_input(match["member_a"]),
            member_topic_input(match["member_b"]),
        ])

    print(f"Opted-in & due: {len(due_nicknames)} / matched this run: {len(matches)}")
    for match in matches:
        print(f"  {match['member_a']} <-> {match['member_b']}  ({DAY_LABELS[match['day_of_week']]}曜{SLOT_LABELS[match['time_slot']]})")
        if match.get("topic"):
            print(f"    topic: {match['topic']}")

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
                message_id = discord_post(channel_id, bot_token, format_announcement(match, match.get("topic")))
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
