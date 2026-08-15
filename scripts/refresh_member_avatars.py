#!/usr/bin/env python3
"""Mirror member_profiles avatar_url into Supabase Storage so it stops breaking.

Problem: member_profiles.avatar_url historically stored a live Discord CDN
link (https://cdn.discordapp.com/avatars/<user_id>/<avatar_hash>.png). That
hash changes whenever the member updates their Discord profile picture, so
the old URL starts 404ing and the member's photo silently disappears from
the directory (see りりぃ, 2026-08-16).

Fix: download the member's current Discord avatar and re-upload it to the
member-avatars Storage bucket (same bucket member_locations already uses,
see upload_member_avatars.py) under a nickname-keyed path that never
changes, then point avatar_url at that stable Storage URL instead. Re-run
this script periodically (see .github/workflows/refresh-member-avatars.yml)
to pick up new Discord avatars over time -- each run just re-uploads to the
same path (upsert), so avatar_url itself never needs to change again.

member_profiles deliberately does not store Discord user IDs (see the table
comment), so the member's current user ID/avatar hash is re-derived each run
from the Discord message linked by self_intro_url (the self-introduction
post), the same ephemeral lookup fetch_self_intros.py already does. Members
with no self_intro_url on file (a handful of early manual entries) keep
whatever avatar_url they already have; they are not part of the 404 bug
since that URL isn't a live Discord link to begin with once migrated once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import upload_member_avatars as avatar_uploads

USER_AGENT = "fire-community-map-avatar-refresh/0.1"
DISCORD_API_BASE = "https://discord.com/api/v10"
SELF_INTRO_URL_RE = re.compile(r"discord\.com/channels/(\d+)/(\d+)/(\d+)")


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


def supabase_get(supabase_url: str, service_role_key: str, path: str) -> list[dict[str, Any]]:
    req = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/{path}",
        headers={"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}", "User-Agent": USER_AGENT},
    )
    with urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def supabase_patch_avatar(supabase_url: str, service_role_key: str, nickname: str, avatar_url: str) -> None:
    req = Request(
        f"{supabase_url.rstrip('/')}/rest/v1/member_profiles?nickname=eq.{quote(nickname)}",
        data=json.dumps({"avatar_url": avatar_url}).encode("utf-8"),
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
            "User-Agent": USER_AGENT,
        },
        method="PATCH",
    )
    with urlopen(req, timeout=30):
        pass


def fetch_discord_message(token: str, channel_id: str, message_id: str) -> dict[str, Any] | None:
    req = Request(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
    )
    while True:
        try:
            with urlopen(req, timeout=30) as res:
                return json.loads(res.read())
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
            return None
        except URLError:
            return None


def current_discord_avatar_url(token: str, self_intro_url: str) -> str | None:
    match = SELF_INTRO_URL_RE.search(self_intro_url)
    if not match:
        return None
    _, channel_id, message_id = match.groups()
    message = fetch_discord_message(token, channel_id, message_id)
    if not message:
        return None
    author = message.get("author") or {}
    user_id = author.get("id")
    avatar_hash = author.get("avatar")
    if not user_id or not avatar_hash:
        return None
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"


def build_storage_path(nickname: str, content_type: str) -> str:
    digest = hashlib.sha256(nickname.encode("utf-8")).hexdigest()[:16]
    ext = avatar_uploads.ALLOWED_CONTENT_TYPES.get(content_type, "png")
    return f"member-profiles/{digest}.{ext}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh member_profiles.avatar_url into stable Storage URLs.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--bucket", default=avatar_uploads.DEFAULT_BUCKET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    discord_token = require_env("DISCORD_BOT_TOKEN")

    if not args.dry_run:
        avatar_uploads.ensure_bucket(supabase_url, service_role_key, args.bucket, public=True)

    members = supabase_get(
        supabase_url,
        service_role_key,
        "member_profiles?select=nickname,avatar_url,self_intro_url&self_intro_url=not.is.null",
    )
    print(f"{len(members)} members with self_intro_url set.")

    updated = 0
    unchanged = 0
    failed: list[tuple[str, str]] = []

    for member in members:
        nickname = member["nickname"]
        self_intro_url = member["self_intro_url"]
        source_url = current_discord_avatar_url(discord_token, self_intro_url)
        if not source_url:
            failed.append((nickname, "no current Discord avatar (message/author/avatar not found)"))
            continue

        try:
            body, content_type = avatar_uploads.download_avatar(source_url, avatar_uploads.MAX_AVATAR_BYTES)
        except RuntimeError as exc:
            failed.append((nickname, f"download failed: {exc}"))
            continue

        storage_path = build_storage_path(nickname, content_type)
        public_url = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{args.bucket}/{storage_path}"

        if args.dry_run:
            print(f"[dry-run] {nickname}: {member.get('avatar_url')!r} -> {public_url!r}")
            continue

        avatar_uploads.upload_object(supabase_url, service_role_key, args.bucket, storage_path, body, content_type)
        if member.get("avatar_url") != public_url:
            supabase_patch_avatar(supabase_url, service_role_key, nickname, public_url)
            updated += 1
        else:
            unchanged += 1

    print(f"\nUpdated {updated}, unchanged {unchanged}, failed {len(failed)}.")
    for nickname, reason in failed:
        print(f"  FAILED {nickname}: {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
