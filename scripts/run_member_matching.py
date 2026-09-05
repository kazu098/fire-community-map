#!/usr/bin/env python3
"""Availability-based random matching batch (ゆるマッチング).

Groups opted-in members whose availability (weekday x time-of-day slot)
overlaps, at random -- no tag/embedding similarity involved. See GitHub
issue #76 for the design background. Groups are always exactly GROUP_SIZE
members (4); if fewer than that many compatible members are found in a
given run, no group is formed for them this round -- no fallback to a
smaller group.

For each member whose matching interval has elapsed (member_matching_settings
.last_matched_at + interval_days <= today, or never matched):
  1. Collect their registered availability slots (member_availability).
  2. Randomly group eligible members who all share at least one slot,
     skipping any pair that was grouped together within the cooldown
     window (member_match_groups / member_match_group_members).
  3. Record the group in member_match_groups(+member_match_group_members)
     and bump last_matched_at for every member in it.
  4. Post an announcement to the Discord matching channel, if configured.

The announcement is written in the voice of the community mascot ふぁいにゃ
(see docs/fainya-persona.md) and includes conversation-starter suggestions
derived from the group's shared tags (member_tags) and self-introductions
(member_profiles.self_intro_text): one for the whole group, plus one for
each 2-member combination within it (shown by default alongside the group
topic, not only as a fallback -- two members hitting it off while a third
listens in is part of the fun), so the match feels less like a cold random
pairing.

The dedicated Discord matching channel does not exist yet (pending
agreement), so --post-to-discord is opt-in and the script no-ops the
Discord step -- logging what it would have posted -- when
DISCORD_MATCHING_CHANNEL_ID is unset. Run with --dry-run to preview matches
without writing to Supabase or posting to Discord.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-member-matching/0.1"
COOLDOWN_DAYS = 60  # avoid re-grouping the same pair within this window
GROUP_SIZE = 4  # fixed group size; no fallback to smaller groups, see run_matching
SCHEDULE_CONFIRM_THRESHOLD = 3  # of 4 group members reacting to the same date option

JST = ZoneInfo("Asia/Tokyo")

DAY_LABELS = {
    "mon": "月", "tue": "火", "wed": "水", "thu": "木",
    "fri": "金", "sat": "土", "sun": "日",
}
SLOT_LABELS = {"morning": "午前", "afternoon": "午後", "evening": "夜"}
# Weekday index (Monday=0, matching datetime.weekday()) for each day_of_week key.
DAY_TO_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
# A concrete clock time (JST) to propose for each loose time_slot, since availability
# is only ever collected as a slot, not an exact time.
SLOT_TIMES = {"morning": (10, 0), "afternoon": (14, 0), "evening": (21, 0)}
DATE_OPTION_EMOJI = ["1️⃣", "2️⃣", "3️⃣"]

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
                return f"「{sorted(overlap)[0]}」について、{a['nickname']}さんが{b['nickname']}さんの力になれそうです"
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
            return f"共通の{label}「{sorted(common)[0]}」の話で盛り上がれそうです"
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
        return f"自己紹介を読むと「{sorted(common)[0]}」が共通の話題になりそうです"
    return None


def _note_writers_topic(members: list[dict[str, Any]]) -> str | None:
    """A light, low-stakes icebreaker: everyone in the group has a note link registered."""
    if all(any("note.com" in (link.get("url") or "") for link in m.get("links", [])) for m in members):
        return "みんなnoteをやっているみたいなので、記事を見せ合うのも面白そうです"
    return None


def _same_prefecture_topic(members: list[dict[str, Any]]) -> str | None:
    prefectures = {m.get("prefecture") for m in members}
    if len(prefectures) == 1 and None not in prefectures:
        return f"実は{next(iter(prefectures))}在住どうし、というのも面白い共通点です"
    return None


def _no_avatar_twins_topic(members: list[dict[str, Any]]) -> str | None:
    """Purely for a laugh: nobody in the group has set a profile photo yet."""
    if len(members) >= 2 and all(not m.get("has_avatar") for m in members):
        return "ちなみにお二人ともアイコン未設定どうし、というのもちょっとおもしろいです"
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
        return "お互いの自己紹介を読んでみると、意外な共通点が見つかるかもしれません"
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


def discord_post(channel_id: str, token: str, content: str, mentioned_user_ids: list[str] | None = None) -> str | None:
    body: dict[str, Any] = {"content": content}
    # Explicit allowlist: only the matched members' <@id> mentions in the content actually
    # ping, nothing else in the text (e.g. an accidental @everyone-looking substring) does.
    body["allowed_mentions"] = {"parse": [], "users": mentioned_user_ids or []}
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
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
            payload = json.loads(res.read().decode("utf-8"))
            return payload.get("id")
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} posting to channel {channel_id}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed posting to channel {channel_id}: {exc}") from exc


def fetch_guild_member_ids_by_display_name(token: str, guild_id: str) -> dict[str, str]:
    """Discord display name (nickname, else global display name, else username) -> user id.

    A name that resolves to more than one member is dropped rather than guessed at, since a
    wrong @mention pings the wrong person -- same caution as scripts/match_discord_avatars.py.
    """
    by_name: dict[str, list[str]] = {}
    after = "0"
    headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
    while True:
        req = Request(
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members?{urlencode({'limit': '1000', 'after': after})}",
            headers=headers,
        )
        with urlopen(req, timeout=30) as res:
            payload = json.loads(res.read().decode("utf-8"))
        if not payload:
            break
        for item in payload:
            user = item.get("user") or {}
            user_id = str(user.get("id") or "")
            if not user_id:
                continue
            display_name = str(item.get("nick") or user.get("global_name") or user.get("username") or "").strip()
            if display_name:
                by_name.setdefault(display_name, []).append(user_id)
        after = str((payload[-1].get("user") or {}).get("id") or after)
        if len(payload) < 1000:
            break
    return {name: ids[0] for name, ids in by_name.items() if len(ids) == 1}


# Site nicknames often carry a trailing emoji/decoration (e.g. "みかん🍊") that a member's
# actual Discord display name doesn't (e.g. "みかん０"), which breaks an exact-match lookup.
# Strip anything after the last run of word/kana/kanji characters so "みかん🍊" -> "みかん".
_TRAILING_DECORATION_RE = re.compile(r"[^\w぀-ヿ㐀-鿿]+$")


def _strip_trailing_decoration(name: str) -> str:
    return _TRAILING_DECORATION_RE.sub("", name).strip()


def load_discord_name_overrides(path: Path) -> dict[str, str]:
    """De-decorated site nickname -> curated Discord display name, from config/member_discord_name_map.csv.

    That CSV already exists for scripts/match_discord_avatars.py's exact same problem (site
    nickname vs. actual Discord display name mismatches); reusing it here means one fix in one
    place instead of maintaining the mapping twice.
    """
    if not path.exists():
        return {}
    overrides: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            form_nickname = (row.get("form_nickname") or "").strip()
            discord_display_name = (row.get("discord_display_name") or "").strip()
            if not form_nickname or not discord_display_name:
                continue
            overrides.setdefault(_strip_trailing_decoration(form_nickname), discord_display_name)
    return overrides


def resolve_discord_user_ids(
    nicknames: list[str],
    guild_display_name_ids: dict[str, str],
    name_overrides: dict[str, str],
) -> dict[str, str]:
    """Site nickname -> Discord user id, trying an exact match first, then the curated override map."""
    resolved: dict[str, str] = {}
    for nickname in nicknames:
        user_id = guild_display_name_ids.get(nickname)
        if not user_id:
            override_display_name = name_overrides.get(_strip_trailing_decoration(nickname))
            if override_display_name:
                user_id = guild_display_name_ids.get(override_display_name)
        if user_id:
            resolved[nickname] = user_id
    return resolved


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


def excluded_pairs_from_recent_groups(group_members: list[dict[str, Any]]) -> set[frozenset[str]]:
    """Every 2-member combination that has appeared together in the same recent group.

    `group_members` should already be filtered to groups created within the cooldown window
    (rows of {"group_id": ..., "member_nickname": ...}).
    """
    by_group: dict[str, list[str]] = {}
    for row in group_members:
        by_group.setdefault(row["group_id"], []).append(row["member_nickname"])
    pairs: set[frozenset[str]] = set()
    for members in by_group.values():
        for a, b in itertools.combinations(members, 2):
            pairs.add(frozenset((a, b)))
    return pairs


def pairwise_topics(members: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Topic suggestions for every 2-member combination within the group.

    Shown by default alongside the group-wide topic (not only when the group has none) --
    two members hitting it off while a third listens in is part of the fun.
    """
    results = []
    for a, b in itertools.combinations(members, 2):
        topic = build_topic_suggestion([a, b])
        if topic:
            results.append((a["nickname"], b["nickname"], topic))
    return results


def run_matching(
    eligible_nicknames: list[str],
    slot_index: dict[str, set[tuple[str, str]]],
    excluded_pairs: set[frozenset[str]],
    rng: random.Random,
    group_size: int = GROUP_SIZE,
) -> list[dict[str, Any]]:
    """Randomly group eligible members into exactly group_size-sized groups who all share an
    availability slot.

    Greedy: shuffle the pool, then for each still-unmatched member, greedily add compatible
    candidates (a slot shared with everyone already in the group, and no recent-cooldown pair
    with anyone already in the group) until group_size is reached or candidates run out. No
    fallback to a smaller group: if fewer than group_size compatible members are found this
    round, the attempt is discarded (not added to results, members stay unmatched) rather than
    posting an undersized group -- a member left over this round is still eligible as a
    candidate for someone else's group later in the same pass, and remains a candidate for
    the next scheduled run either way.
    """
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
        rng.shuffle(candidates)

        group = [nickname]
        common_slots = set(slot_index[nickname])
        for candidate in candidates:
            if len(group) >= group_size:
                break
            overlap = common_slots & slot_index[candidate]
            if not overlap:
                continue
            if any(frozenset((candidate, member)) in excluded_pairs for member in group):
                continue
            group.append(candidate)
            common_slots = overlap

        if len(group) < group_size:
            continue

        day_of_week, time_slot = rng.choice(sorted(common_slots))
        results.append({
            "members": group,
            "day_of_week": day_of_week,
            "time_slot": time_slot,
        })
        matched.update(group)

    return results


def format_announcement(
    match: dict[str, Any],
    group_topic: str | None,
    pair_topics: list[tuple[str, str, str]],
    discord_user_ids: dict[str, str] | None = None,
) -> str:
    """Render the Discord announcement in ふぁいにゃ's voice (docs/fainya-persona.md).

    discord_user_ids maps member nickname -> Discord user id; a member found there gets an
    actual <@id> @mention (so they're notified), others fall back to a plain bold name.
    """
    members = match["members"]
    day = DAY_LABELS.get(match["day_of_week"], match["day_of_week"])
    slot = SLOT_LABELS.get(match["time_slot"], match["time_slot"])
    discord_user_ids = discord_user_ids or {}

    def mention(nickname: str) -> str:
        user_id = discord_user_ids.get(nickname)
        return f"<@{user_id}>" if user_id else f"**{nickname}** さん"

    names = "、".join(mention(n) for n in members)
    lines = [
        f"🐾 {names}がマッチしましたにゃ！",
        f"みなさんとも「{day}曜{slot}」が空いているみたいです。",
    ]

    topic_lines = []
    if group_topic:
        label = "(全員) " if len(members) > 2 else ""
        topic_lines.append(f"{label}{group_topic}")
    for a, b, topic in pair_topics:
        if topic == group_topic:
            continue  # already covered by the (全員) line above
        topic_lines.append(f"({a}さん×{b}さん) {topic}")
    if topic_lines:
        lines.append("")
        lines.append("💡 盛り上がりそうな話題:")
        lines.extend(f"- {t}" for t in topic_lines)

    return "\n".join(lines)


def next_occurrences(day_of_week: str, time_slot: str, now: datetime, count: int = 3) -> list[datetime]:
    """The next `count` occurrences of day_of_week at the slot's fixed clock time (JST), one
    week apart, starting from the first one at least a day out (so there's notice to plan)."""
    now_jst = now.astimezone(JST)
    hour, minute = SLOT_TIMES[time_slot]
    target_weekday = DAY_TO_WEEKDAY[day_of_week]
    days_ahead = (target_weekday - now_jst.weekday()) % 7
    first = now_jst.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    if first <= now_jst + timedelta(days=1):
        first += timedelta(days=7)
    return [first + timedelta(weeks=i) for i in range(count)]


WEEKDAY_KANJI = ["月", "火", "水", "木", "金", "土", "日"]
OPTION_NUMBERS = ["①", "②", "③"]


def format_schedule_proposal(day_of_week: str, time_slot: str, dates: list[datetime]) -> str:
    day = DAY_LABELS.get(day_of_week, day_of_week)
    slot = SLOT_LABELS.get(time_slot, time_slot)
    lines = [f"🐾 {day}曜{slot}が共通しているみたいです！日程を決めましょう。", ""]
    for number, date in zip(OPTION_NUMBERS, dates):
        weekday_kanji = WEEKDAY_KANJI[date.weekday()]
        lines.append(f"{number} {date.month}/{date.day}({weekday_kanji}) {date.hour:02d}:{date.minute:02d}〜")
    lines.append("")
    lines.append(f"行ける日にリアクションで教えてください🙏 {SCHEDULE_CONFIRM_THRESHOLD}人以上集まったら開催決定です🎉")
    return "\n".join(lines)


def discord_add_reaction(channel_id: str, message_id: str, token: str, emoji: str) -> None:
    encoded_emoji = quote(emoji)
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me",
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
        method="PUT",
    )
    try:
        with urlopen(req, timeout=30):
            pass
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} adding reaction {emoji} to {message_id}: {body_text}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed adding reaction {emoji} to {message_id}: {exc}") from exc


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
    recent_groups = get(
        f"/rest/v1/member_match_groups?select=id&created_at=gte.{quote((now - timedelta(days=COOLDOWN_DAYS)).isoformat())}"
    )
    recent_group_ids = [g["id"] for g in recent_groups]
    recent_group_members = (
        get(f"/rest/v1/member_match_group_members?select=group_id,member_nickname&group_id=in.({','.join(recent_group_ids)})")
        if recent_group_ids else []
    )
    member_tags = get("/rest/v1/member_tags?select=member_nickname,category,value")
    profiles = get("/rest/v1/member_profiles?select=nickname,self_intro_text,avatar_url")
    member_links = get("/rest/v1/member_links?select=member_nickname,label,url")
    member_locations = get("/rest/v1/member_locations?select=nickname,prefecture")

    due_nicknames = [s["member_nickname"] for s in settings if is_due(s, now)]
    slot_index = build_slot_index(availability)
    excluded_pairs = excluded_pairs_from_recent_groups(recent_group_members)

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
        member_inputs = [member_topic_input(n) for n in match["members"]]
        match["group_topic"] = build_topic_suggestion(member_inputs)
        match["pair_topics"] = pairwise_topics(member_inputs) if len(member_inputs) > 2 else []

    print(f"Opted-in & due: {len(due_nicknames)} / matched this run: {len(matches)}")
    for match in matches:
        names = " / ".join(match["members"])
        print(f"  {names}  ({DAY_LABELS[match['day_of_week']]}曜{SLOT_LABELS[match['time_slot']]})")
        if match.get("group_topic"):
            print(f"    group topic: {match['group_topic']}")
        for a, b, topic in match.get("pair_topics", []):
            print(f"    {a} x {b}: {topic}")

    if args.dry_run:
        print("--dry-run: no writes to Supabase, no Discord post.")
        return 0

    if not matches:
        return 0

    channel_id = os.environ.get("DISCORD_MATCHING_CHANNEL_ID")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    guild_id = os.environ.get("DISCORD_GUILD_ID")

    discord_user_ids: dict[str, str] = {}
    if args.post_to_discord and bot_token and guild_id:
        guild_display_name_ids = fetch_guild_member_ids_by_display_name(bot_token, guild_id)
        name_overrides = load_discord_name_overrides(Path("config/member_discord_name_map.csv"))
        discord_user_ids = resolve_discord_user_ids(due_nicknames, guild_display_name_ids, name_overrides)

    for match in matches:
        message_id = None
        posted_at = None
        if args.post_to_discord:
            if channel_id and bot_token:
                mentioned_ids = [discord_user_ids[n] for n in match["members"] if n in discord_user_ids]
                content = format_announcement(
                    match, match.get("group_topic"), match.get("pair_topics", []), discord_user_ids,
                )
                message_id = discord_post(channel_id, bot_token, content, mentioned_ids)
                posted_at = datetime.now(timezone.utc).isoformat()
            else:
                print(
                    "DISCORD_MATCHING_CHANNEL_ID is not set yet (channel not created). "
                    "Skipping Discord post; the match is still recorded.",
                )

        group_res = supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/member_match_groups",
            service_role_key,
            body=[{
                "day_of_week": match["day_of_week"],
                "time_slot": match["time_slot"],
                "discord_message_id": message_id,
                "posted_at": posted_at,
            }],
            prefer="return=representation",
        )
        group_id = group_res[0]["id"]

        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/member_match_group_members",
            service_role_key,
            body=[{"group_id": group_id, "member_nickname": n} for n in match["members"]],
            prefer="return=minimal",
        )

        if args.post_to_discord and channel_id and bot_token and message_id:
            dates = next_occurrences(match["day_of_week"], match["time_slot"], now)
            schedule_content = format_schedule_proposal(match["day_of_week"], match["time_slot"], dates)
            schedule_message_id = discord_post(channel_id, bot_token, schedule_content)
            for emoji in DATE_OPTION_EMOJI[: len(dates)]:
                discord_add_reaction(channel_id, schedule_message_id, bot_token, emoji)
            supabase_request(
                "POST",
                f"{supabase_url}/rest/v1/member_match_schedules",
                service_role_key,
                body=[{
                    "group_id": group_id,
                    "proposed_dates": [d.isoformat() for d in dates],
                    "discord_message_id": schedule_message_id,
                }],
                prefer="return=minimal",
            )

        for nickname in match["members"]:
            supabase_request(
                "PATCH",
                f"{supabase_url}/rest/v1/member_matching_settings?member_nickname=eq.{quote(nickname)}",
                service_role_key,
                body={"last_matched_at": now.isoformat()},
                prefer="return=minimal",
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
