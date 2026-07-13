#!/usr/bin/env python3
"""Fetch self-introduction posts for target nicknames from a Discord channel.

Walks the self-introduction channel from the beginning, matches messages to a
list of target nicknames (by Discord display name), and picks the most recent
matching message per person. Writes full text + a permalink for manual review
before it is loaded into Supabase.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://discord.com/api/v10"
USER_AGENT = "fire-community-map-self-intro-sync/0.1"


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


def discord_get(path: str, token: str, query: dict[str, str] | None = None) -> Any:
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    req = Request(
        url,
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
    )
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
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord API error {exc.code} for {path}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Discord API request failed for {path}: {exc}") from exc


def fetch_all_messages(token: str, channel_id: str) -> list[dict[str, Any]]:
    after = "0"
    messages: list[dict[str, Any]] = []
    while True:
        page = discord_get(
            f"/channels/{channel_id}/messages", token, {"limit": "100", "after": after}
        )
        if not page:
            break
        page_sorted = sorted(page, key=lambda item: int(item["id"]))
        messages.extend(page_sorted)
        after = str(page_sorted[-1]["id"])
        if len(page_sorted) < 100:
            break
    return messages


def display_name(message: dict[str, Any]) -> str:
    member = message.get("member") or {}
    author = message.get("author") or {}
    if member.get("nick"):
        return str(member["nick"])
    return str(author.get("global_name") or author.get("username") or "")


def avatar_url(message: dict[str, Any]) -> str | None:
    author = message.get("author") or {}
    user_id = author.get("id")
    avatar_hash = author.get("avatar")
    if not user_id or not avatar_hash:
        return None
    extension = "gif" if str(avatar_hash).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{extension}?size=128"


def normalize(name: str) -> str:
    return re.sub(r"[\s0-9０-９（(].*$", "", name).strip().lower()


SELF_INTRO_MARKERS = (
    "【ニックネーム】",
    "【属性】",
    "【年齢",
    "【現在の仕事",
    "【投資",
)


def declared_nickname(content: str) -> str | None:
    match = re.search(r"【ニックネーム】\s*\n?\s*(?:→\s*)?(.+)", content)
    if not match:
        return None
    value = match.group(1).strip()
    value = value.rstrip("です。、,.!！ 　")
    return value or None


def is_self_intro(message: dict[str, Any]) -> bool:
    content = str(message.get("content") or "").strip()
    hits = sum(1 for marker in SELF_INTRO_MARKERS if marker in content)
    if hits >= 2:
        return True
    if "自己紹介" in content and message.get("attachments"):
        return True
    return False


def find_matches(
    target_nicknames: list[str],
    messages: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_target: dict[str, list[dict[str, Any]]] = {name: [] for name in target_nicknames}
    normalized_targets = {name: normalize(name) for name in target_nicknames}

    for message in messages:
        content = str(message.get("content") or "").strip()
        if not content or not is_self_intro(message):
            continue
        name = display_name(message)
        if not name:
            continue
        declared = declared_nickname(content)

        for target in target_nicknames:
            if name == target or (declared and declared == target):
                by_target[target].append(message)
                break
        else:
            norm_name = normalize(name)
            norm_declared = normalize(declared) if declared else ""
            norm_target_hits = [
                target
                for target, norm_target in normalized_targets.items()
                if norm_target and (norm_target == norm_name or (norm_declared and norm_target == norm_declared))
            ]
            if len(norm_target_hits) == 1:
                by_target[norm_target_hits[0]].append(message)

    return by_target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch self-introduction messages for target nicknames."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--channel-id", default="1389923387887063171")
    parser.add_argument(
        "--nicknames-file",
        default="config/self_intro_target_nicknames.txt",
        help="One nickname per line.",
    )
    parser.add_argument("--output", default="tmp/self_intros.json")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")

    target_nicknames = [
        line.strip()
        for line in Path(args.nicknames_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    messages = fetch_all_messages(token, args.channel_id)
    matches = find_matches(target_nicknames, messages)

    results = []
    for target in target_nicknames:
        candidates = matches.get(target, [])
        if not candidates:
            results.append({"nickname": target, "found": False})
            continue
        latest = max(candidates, key=lambda m: int(m["id"]))
        results.append(
            {
                "nickname": target,
                "found": True,
                "discord_display_name": display_name(latest),
                "discord_message_id": str(latest["id"]),
                "message_url": f"https://discord.com/channels/{guild_id}/{args.channel_id}/{latest['id']}",
                "posted_at": latest.get("timestamp"),
                "content": str(latest.get("content") or "").strip(),
                "attachment_urls": [
                    str(a.get("url")) for a in latest.get("attachments", []) if a.get("url")
                ],
                "avatar_url": avatar_url(latest),
                "candidate_count": len(candidates),
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    found = sum(1 for r in results if r["found"])
    print(f"Matched {found}/{len(target_nicknames)} nicknames. Wrote {output_path}")
    for r in results:
        if not r["found"]:
            print(f"  NOT FOUND: {r['nickname']}")
        elif r["candidate_count"] > 1:
            print(f"  MULTIPLE CANDIDATES ({r['candidate_count']}): {r['nickname']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
