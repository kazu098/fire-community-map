#!/usr/bin/env python3
"""Resolve each member's Discord user id and store it on member_profiles.

Feeds member_profiles.discord_user_id (supabase/member_discord_ids.sql),
which the "相談してみる" (consultation) feature on the member detail page
uses to link out to https://discord.com/users/{id} and open a DM -- Discord
has no way to prefill DM text via URL, so the site only offers a copyable
draft message plus this link; nothing is auto-sent.

Resolution reuses the exact same guild-member-list + curated-override-CSV
approach as scripts/run_member_matching.py's Discord @mentions (which in
turn matches scripts/match_discord_avatars.py's site-nickname-vs-Discord-
display-name problem): an exact display-name match first, then
config/member_discord_name_map.csv for members whose Discord display name
differs from their site nickname (e.g. decorative emoji/suffix).

Only resolved nicknames are written; a member who doesn't resolve this run
keeps whatever value (if any) is already stored, rather than being reset to
null over a transient guild-lookup hiccup.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DISCORD_API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-member-discord-ids/0.1"


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


def fetch_guild_member_ids_by_display_name(token: str, guild_id: str) -> dict[str, str]:
    """Discord display name (nickname, else global display name, else username) -> user id.

    A name that resolves to more than one member is dropped rather than guessed at, since a
    wrong link would open a DM with the wrong person -- same caution as
    scripts/match_discord_avatars.py and scripts/run_member_matching.py.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve member Discord user ids and store them on member_profiles.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and print without writing to Supabase.")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    bot_token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")

    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    req = Request(f"{supabase_url}/rest/v1/member_profiles?select=nickname,discord_user_id", headers=headers)
    with urlopen(req, timeout=30) as res:
        profiles: list[dict[str, Any]] = json.loads(res.read().decode("utf-8"))

    guild_display_name_ids = fetch_guild_member_ids_by_display_name(bot_token, guild_id)
    name_overrides = load_discord_name_overrides(Path("config/member_discord_name_map.csv"))
    nicknames = [p["nickname"] for p in profiles]
    resolved = resolve_discord_user_ids(nicknames, guild_display_name_ids, name_overrides)

    changed = {
        nickname: user_id
        for nickname, user_id in resolved.items()
        if next((p for p in profiles if p["nickname"] == nickname), {}).get("discord_user_id") != user_id
    }

    print(f"Members: {len(profiles)} / resolved this run: {len(resolved)} / to update: {len(changed)}")
    unresolved = [n for n in nicknames if n not in resolved]
    if unresolved:
        print(f"Unresolved ({len(unresolved)}): {', '.join(unresolved)}")

    if args.dry_run:
        print("--dry-run: no writes to Supabase.")
        return 0

    write_headers = {**headers, "Content-Type": "application/json", "Prefer": "return=minimal"}
    for nickname, user_id in changed.items():
        req = Request(
            f"{supabase_url}/rest/v1/member_profiles?nickname=eq.{quote(nickname)}",
            data=json.dumps({"discord_user_id": user_id}).encode("utf-8"),
            headers=write_headers,
            method="PATCH",
        )
        try:
            with urlopen(req, timeout=30):
                pass
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Failed to update discord_user_id for {nickname}: HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Failed to update discord_user_id for {nickname}: {exc}") from exc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
