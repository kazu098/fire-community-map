#!/usr/bin/env python3
"""Fetch Discord #map travel posts and write a static map JSON file."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_BASE = "https://discord.com/api/v10"
GEOLONIA_BASE = "https://geolonia.github.io/japanese-addresses/api/ja"
DISCORD_EPOCH = 1420070400000
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
USER_AGENT = "fire-community-map-travel-sync/0.1"


@dataclass(frozen=True)
class Location:
    prefecture: str
    municipality_optional: str | None
    lat: float
    lng: float
    source: str


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
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord API error {exc.code} for {path}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Discord API request failed for {path}: {exc}") from exc


def download_file(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=60) as res:
            output.write_bytes(res.read())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Attachment download failed {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Attachment download failed: {exc}") from exc


def snowflake_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    millis = int(dt.timestamp() * 1000)
    return str((millis - DISCORD_EPOCH) << 22)


def parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Datetime must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def read_prefectures(path: Path) -> dict[str, Location]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            row["prefecture"].strip(): Location(
                prefecture=row["prefecture"].strip(),
                municipality_optional=None,
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                source="prefecture_static",
            )
            for row in csv.DictReader(f)
            if row.get("prefecture") and row.get("lat") and row.get("lng")
        }


def read_aliases(path: Path) -> dict[str, Location]:
    if not path.exists():
        return {}
    aliases: dict[str, Location] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("input") or "").strip()
            lat = row.get("lat")
            lng = row.get("lng")
            prefecture = (row.get("prefecture") or "").strip()
            if not key or not prefecture or not lat or not lng:
                continue
            aliases[key] = Location(
                prefecture=prefecture,
                municipality_optional=(row.get("municipality_optional") or "").strip() or None,
                lat=float(lat),
                lng=float(lng),
                source=row.get("geocode_source") or "manual_alias",
            )
    return aliases


def geocode_municipality(prefecture: str, municipality: str, cache_dir: Path) -> Location:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{prefecture}_{municipality}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        url = f"{GEOLONIA_BASE}/{quote(prefecture)}/{quote(municipality)}.json"
        req = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(req, timeout=30) as res:
                payload = json.loads(res.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Geolonia API error {exc.code} for {prefecture}{municipality}") from exc
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    points = [
        (float(row["lat"]), float(row["lng"]))
        for row in payload
        if row.get("lat") is not None and row.get("lng") is not None
    ]
    if not points:
        raise RuntimeError(f"Geolonia returned no points for {prefecture}{municipality}")
    lat = sum(point[0] for point in points) / len(points)
    lng = sum(point[1] for point in points) / len(points)
    return Location(
        prefecture=prefecture,
        municipality_optional=municipality,
        lat=round(lat, 6),
        lng=round(lng, 6),
        source="geolonia",
    )


def detect_location(
    text: str,
    aliases: dict[str, Location],
    prefectures: dict[str, Location],
    cache_dir: Path,
) -> Location | None:
    compact = re.sub(r"\s+", "", text)

    for key in sorted(aliases, key=len, reverse=True):
        if key and key in compact:
            return aliases[key]

    for prefecture in sorted(prefectures, key=len, reverse=True):
        municipality_match = re.search(re.escape(prefecture) + r"(.+?[市区町村])", compact)
        if municipality_match:
            municipality = municipality_match.group(1)
            try:
                return geocode_municipality(prefecture, municipality, cache_dir)
            except RuntimeError:
                return prefectures[prefecture]

    for pref, location in sorted(prefectures.items(), key=lambda item: len(item[0]), reverse=True):
        if pref in compact or pref.removesuffix("県").removesuffix("府").removesuffix("都").removesuffix("道") in compact:
            return location

    return None


def find_channel_id(channels: list[dict[str, Any]], channel_name: str) -> str:
    normalized = channel_name.lstrip("#")
    matches = [
        c for c in channels
        if c.get("type") == 0 and c.get("name") in {normalized, channel_name}
    ]
    if not matches:
        contains = [
            c for c in channels
            if c.get("type") == 0 and normalized in str(c.get("name", ""))
        ]
        if contains:
            matches = contains
    if len(matches) != 1:
        names = ", ".join(sorted(str(c.get("name")) for c in channels if c.get("type") == 0))
        raise SystemExit(f"Could not uniquely find channel '{channel_name}'. Text channels: {names}")
    return str(matches[0]["id"])


def image_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    images = []
    for attachment in message.get("attachments", []):
        filename = str(attachment.get("filename") or "")
        content_type = str(attachment.get("content_type") or "")
        suffix = Path(filename).suffix.lower()
        if content_type.startswith("image/") or suffix in IMAGE_EXTENSIONS:
            images.append(attachment)
    return images


def safe_slug(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return digest


def map_relative(path: Path) -> Path:
    try:
        return path.relative_to("map")
    except ValueError:
        return path


def display_name(author: dict[str, Any], member: dict[str, Any] | None) -> str:
    if member and member.get("nick"):
        return str(member["nick"])
    return str(author.get("global_name") or author.get("username") or "unknown")


def avatar_url(author: dict[str, Any]) -> str | None:
    user_id = author.get("id")
    avatar_hash = author.get("avatar")
    if not user_id or not avatar_hash:
        return None
    extension = "gif" if str(avatar_hash).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{extension}?size=128"


def build_post(
    message: dict[str, Any],
    location: Location,
    photos: list[str],
    avatar_path: str | None,
) -> dict[str, Any]:
    author = message.get("author", {})
    member = message.get("member")
    content = str(message.get("content") or "").strip()
    cleaned = re.sub(r"(?i)(^|\s)#map(\s|$)", " ", content).strip()
    posted_at = datetime.fromisoformat(str(message["timestamp"]).replace("Z", "+00:00"))
    return {
        "discord_message_id": str(message["id"]),
        "nickname": display_name(author, member),
        "avatar_path": avatar_path,
        "avatarColor": "#f97316",
        "init": display_name(author, member)[:1] or "?",
        "prefecture": location.prefecture,
        "municipality_optional": location.municipality_optional,
        "lat": location.lat,
        "lng": location.lng,
        "date": posted_at.astimezone().strftime("%Y/%m/%d"),
        "posted_at": posted_at.isoformat(),
        "comment": cleaned,
        "photos": photos,
        "location_source": location.source,
    }


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_posts(existing: list[dict[str, Any]], new_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(post["discord_message_id"]): post
        for post in existing
        if post.get("discord_message_id")
    }
    for post in new_posts:
        by_id[str(post["discord_message_id"])] = post
    merged = list(by_id.values())
    merged.sort(key=lambda item: item.get("posted_at", ""), reverse=True)
    return merged


def fetch_messages(
    token: str,
    channel_id: str,
    after_id: str,
    end: datetime | None,
) -> list[dict[str, Any]]:
    after = after_id
    before = snowflake_from_datetime(end) if end else None
    messages: list[dict[str, Any]] = []

    while True:
        query = {"limit": "100", "after": after}
        if before:
            query["before"] = before
        page = discord_get(f"/channels/{channel_id}/messages", token, query)
        if not page:
            break
        page_sorted = sorted(page, key=lambda item: int(item["id"]))
        messages.extend(page_sorted)
        after = str(page_sorted[-1]["id"])
        if len(page_sorted) < 100:
            break

    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Discord #map travel posts into data/travel_posts.json.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--channel-name", default="旅行")
    parser.add_argument("--channel-id")
    parser.add_argument(
        "--since",
        type=parse_datetime,
        help="Initial fetch start time. Required only when no sync state exists, or when --reset-state is used.",
    )
    parser.add_argument("--until", type=parse_datetime)
    parser.add_argument("--prefectures", default="config/prefecture_centroids.csv")
    parser.add_argument("--aliases", default="config/location_aliases.csv")
    parser.add_argument("--cache-dir", default="tmp/geolonia_cache")
    parser.add_argument("--output", default="data/travel_posts.json")
    parser.add_argument("--state-file", default="data/travel_sync_state.json")
    parser.add_argument("--photos-dir", default="data/travel-photos")
    parser.add_argument("--avatar-dir", default="data/travel-avatars")
    parser.add_argument("--reset-state", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    token = require_env("DISCORD_BOT_TOKEN")
    guild_id = require_env("DISCORD_GUILD_ID")

    prefectures = read_prefectures(Path(args.prefectures))
    aliases = read_aliases(Path(args.aliases))

    channel_id = args.channel_id
    if not channel_id:
        channels = discord_get(f"/guilds/{guild_id}/channels", token)
        channel_id = find_channel_id(channels, args.channel_name)

    state_path = Path(args.state_file)
    state = {} if args.reset_state else read_json_file(state_path, {})
    last_scanned_message_id = state.get("last_scanned_message_id")
    if last_scanned_message_id:
        after_id = str(last_scanned_message_id)
        start_source = "state"
    elif args.since:
        after_id = snowflake_from_datetime(args.since)
        start_source = "since"
    else:
        raise SystemExit("No sync state found. Pass --since 2026-06-28T22:00:00+09:00 for the first run.")

    messages = fetch_messages(token, channel_id, after_id, args.until)
    photos_dir = Path(args.photos_dir)
    avatar_dir = Path(args.avatar_dir)
    new_posts: list[dict[str, Any]] = []
    skipped_no_map = 0
    skipped_no_location = 0
    skipped_no_images = 0

    for message in messages:
        content = str(message.get("content") or "")
        if not re.search(r"(?i)(^|\s)#map(\s|$)", content):
            skipped_no_map += 1
            continue

        attachments = image_attachments(message)
        if not attachments:
            skipped_no_images += 1
            continue

        location = detect_location(content, aliases, prefectures, Path(args.cache_dir))
        if not location:
            skipped_no_location += 1
            continue

        message_id = str(message["id"])
        photo_paths: list[str] = []
        for index, attachment in enumerate(attachments, start=1):
            filename = str(attachment.get("filename") or f"photo-{index}.jpg")
            suffix = Path(filename).suffix.lower() or ".jpg"
            output_path = photos_dir / f"{message_id}-{index}{suffix}"
            if not args.dry_run:
                download_file(str(attachment["url"]), output_path)
            photo_paths.append(map_relative(output_path).as_posix())

        avatar_path = None
        author_avatar = avatar_url(message.get("author", {}))
        if author_avatar:
            output_avatar = avatar_dir / f"{safe_slug(message_id)}.png"
            if not args.dry_run:
                download_file(author_avatar, output_avatar)
            avatar_path = map_relative(output_avatar).as_posix()

        new_posts.append(build_post(message, location, photo_paths, avatar_path))

    existing_posts = read_json_file(Path(args.output), [])
    if not isinstance(existing_posts, list):
        raise SystemExit(f"{args.output} must contain a JSON array.")
    posts = merge_posts(existing_posts, new_posts)

    newest_scanned_id = max((str(message["id"]) for message in messages), key=int, default=str(after_id))
    newest_imported_id = max((str(post["discord_message_id"]) for post in posts), key=int, default=None)
    next_state = {
        "channel_id": str(channel_id),
        "last_scanned_message_id": newest_scanned_id,
        "last_imported_message_id": newest_imported_id,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
    }

    if not args.dry_run:
        write_json_file(Path(args.output), posts)
        write_json_file(state_path, next_state)

    summary = {
        "channel_id": channel_id,
        "start_source": start_source,
        "after_id": after_id,
        "messages_scanned": len(messages),
        "new_posts": len(new_posts),
        "posts_written": len(posts),
        "skipped_no_map": skipped_no_map,
        "skipped_no_images": skipped_no_images,
        "skipped_no_location": skipped_no_location,
        "output": args.output,
        "state_file": args.state_file,
        "next_state": next_state,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
