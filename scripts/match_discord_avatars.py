#!/usr/bin/env python3
"""Match Google Form nicknames to Discord members and emit avatar candidates."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://discord.com/api/v10"
CDN_BASE = "https://cdn.discordapp.com"
USER_AGENT = "fire-community-map-avatar-sync/0.1"


@dataclass(frozen=True)
class SheetMember:
    row_number: int
    nickname: str
    location_text: str


@dataclass(frozen=True)
class DiscordMember:
    display_name: str
    avatar_url: str
    avatar_hash: str | None
    avatar_source: str
    is_bot: bool
    username: str
    global_name: str | None
    nick: str | None
    user_id: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def http_get_text(url: str, headers: dict[str, str] | None = None) -> str:
    request_headers = {"User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP error {exc.code} fetching {url}: {body}") from exc
    except URLError as exc:
        raise SystemExit(f"Request failed fetching {url}: {exc}") from exc


def discord_get_json(path: str, token: str, query: dict[str, str] | None = None) -> Any:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"

    request = Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": USER_AGENT,
        },
    )
    while True:
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
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
            body = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Discord API error {exc.code}: {body}") from exc
        except URLError as exc:
            raise SystemExit(f"Discord API request failed: {exc}") from exc


def read_members_csv(path: Path) -> list[SheetMember]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows_to_sheet_members(rows)


def read_name_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    name_map: dict[str, str] = {}
    for row in rows:
        form_nickname = (row.get("form_nickname") or "").strip()
        discord_display_name = (row.get("discord_display_name") or "").strip()
        if form_nickname and discord_display_name:
            name_map[form_nickname] = discord_display_name
    return name_map


def read_sheet_members(sheet_id: str, sheet_name: str) -> list[SheetMember]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        f"{urlencode({'tqx': 'out:csv', 'sheet': sheet_name})}"
    )
    text = http_get_text(url)
    rows = list(csv.reader(text.splitlines()))
    return rows_to_sheet_members(rows)


def rows_to_sheet_members(rows: list[list[str]]) -> list[SheetMember]:
    if not rows:
        return []

    members: list[SheetMember] = []
    for index, row in enumerate(rows[1:], start=2):
        nickname = row[1].strip() if len(row) > 1 else ""
        location_text = row[3].strip() if len(row) > 3 else ""
        if not nickname:
            continue
        members.append(
            SheetMember(
                row_number=index,
                nickname=nickname,
                location_text=location_text,
            )
        )
    return members


def list_discord_members(token: str, guild_id: str, include_bots: bool) -> list[DiscordMember]:
    members: list[DiscordMember] = []
    after = "0"

    while True:
        payload = discord_get_json(
            f"/guilds/{guild_id}/members",
            token,
            {"limit": "1000", "after": after},
        )
        if not isinstance(payload, list):
            raise SystemExit(f"Unexpected Discord response: {payload!r}")
        if not payload:
            break

        for item in payload:
            user = item.get("user") or {}
            user_id = str(user.get("id") or "")
            if not user_id:
                continue
            is_bot = bool(user.get("bot"))
            if is_bot and not include_bots:
                continue

            username = str(user.get("username") or "")
            global_name = user.get("global_name")
            nick = item.get("nick")
            display_name = str(nick or global_name or username).strip()
            avatar_hash, avatar_url, avatar_source = build_avatar(item, user, guild_id, user_id)

            members.append(
                DiscordMember(
                    display_name=display_name,
                    avatar_url=avatar_url,
                    avatar_hash=avatar_hash,
                    avatar_source=avatar_source,
                    is_bot=is_bot,
                    username=username,
                    global_name=global_name,
                    nick=nick,
                    user_id=user_id,
                )
            )

        after = str((payload[-1].get("user") or {}).get("id") or after)
        if len(payload) < 1000:
            break

    return members


def build_avatar(
    member: dict[str, Any],
    user: dict[str, Any],
    guild_id: str,
    user_id: str,
) -> tuple[str | None, str, str]:
    member_avatar = member.get("avatar")
    if member_avatar:
        ext = "gif" if str(member_avatar).startswith("a_") else "png"
        return (
            str(member_avatar),
            f"{CDN_BASE}/guilds/{guild_id}/users/{user_id}/avatars/{member_avatar}.{ext}?size=128",
            "guild_member",
        )

    user_avatar = user.get("avatar")
    if user_avatar:
        ext = "gif" if str(user_avatar).startswith("a_") else "png"
        return (
            str(user_avatar),
            f"{CDN_BASE}/avatars/{user_id}/{user_avatar}.{ext}?size=128",
            "user",
        )

    index = (int(user_id) >> 22) % 6
    return None, f"{CDN_BASE}/embed/avatars/{index}.png", "default"


def match_members(
    sheet_members: list[SheetMember],
    discord_members: list[DiscordMember],
    include_discord_user_id: bool,
    name_map: dict[str, str],
) -> dict[str, Any]:
    by_display_name: dict[str, list[DiscordMember]] = {}
    for member in discord_members:
        if not member.display_name:
            continue
        by_display_name.setdefault(member.display_name, []).append(member)

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    duplicate_matches: list[dict[str, Any]] = []

    for sheet_member in sheet_members:
        lookup_name = name_map.get(sheet_member.nickname, sheet_member.nickname)
        match_method = "manual_map" if lookup_name != sheet_member.nickname else "exact"
        candidates = by_display_name.get(lookup_name, [])
        base = {
            "sheet_row": sheet_member.row_number,
            "nickname": sheet_member.nickname,
            "location_text": sheet_member.location_text,
            "discord_lookup_name": lookup_name,
            "match_method": match_method,
        }

        if len(candidates) == 1:
            matched.append(base | discord_member_payload(candidates[0], include_discord_user_id))
        elif len(candidates) > 1:
            duplicate_matches.append(
                base
                | {
                    "candidate_count": len(candidates),
                    "candidates": [
                        discord_member_payload(candidate, include_discord_user_id)
                        for candidate in candidates
                    ],
                }
            )
        else:
            unmatched.append(base)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "sheet_members": len(sheet_members),
            "discord_members": len(discord_members),
            "matched": len(matched),
            "unmatched": len(unmatched),
            "duplicate_matches": len(duplicate_matches),
        },
        "matched": matched,
        "unmatched": unmatched,
        "duplicate_matches": duplicate_matches,
    }


def discord_member_payload(member: DiscordMember, include_discord_user_id: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "discord_display_name": member.display_name,
        "discord_username": member.username,
        "discord_global_name": member.global_name,
        "discord_nick": member.nick,
        "avatar_url": member.avatar_url,
        "avatar_hash": member.avatar_hash,
        "avatar_source": member.avatar_source,
    }
    if include_discord_user_id:
        payload["discord_user_id"] = member.user_id
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Match Google Form nicknames to Discord member avatars."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--members-csv",
        default=os.environ.get("MEMBER_SOURCE_CSV"),
        help=(
            "Optional local CSV export of the Google Form responses. "
            "When omitted, the script reads GOOGLE_SHEET_ID via Google Sheets CSV export."
        ),
    )
    parser.add_argument("--output", default="tmp/member_avatar_matches.json")
    parser.add_argument(
        "--name-map",
        default="config/member_discord_name_map.csv",
        help=(
            "CSV with form_nickname,discord_display_name columns for confirmed "
            "manual mappings. The output nickname remains the Google Form nickname."
        ),
    )
    parser.add_argument("--include-bots", action="store_true")
    parser.add_argument("--include-discord-user-id", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")
    if args.members_csv:
        sheet_members = read_members_csv(Path(args.members_csv))
    else:
        sheet_id = require_env("GOOGLE_SHEET_ID")
        sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Form Responses 1")
        sheet_members = read_sheet_members(sheet_id, sheet_name)
    name_map = read_name_map(Path(args.name_map) if args.name_map else None)
    discord_members = list_discord_members(token, guild_id, args.include_bots)
    report = match_members(
        sheet_members,
        discord_members,
        args.include_discord_user_id,
        name_map,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = report["summary"]
    print(
        "Matched {matched}/{sheet_members} sheet members "
        "({unmatched} unmatched, {duplicate_matches} duplicate matches).".format(**summary)
    )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
