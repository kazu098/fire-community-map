#!/usr/bin/env python3
"""Sync new or changed Google Form member locations into Supabase."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import match_discord_avatars as avatars
import normalize_member_locations as locations
import upload_member_avatars as avatar_uploads


USER_AGENT = "fire-community-map-member-delta-sync/0.1"
SYNC_FIELDS = (
    "location_text",
    "prefecture",
    "municipality_optional",
    "location_level",
    "lat",
    "lng",
    "map_lat",
    "map_lng",
    "geocode_source",
)
CHANGE_FIELDS = (
    "location_text",
    "prefecture",
    "municipality_optional",
    "location_level",
    "lat",
    "lng",
    "geocode_source",
)


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


def parse_sheet_id(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", sheet_url)
    if not match:
        raise SystemExit(f"Could not parse Google Sheet ID from URL: {sheet_url}")
    return match.group(1)


def read_source_members(args: argparse.Namespace) -> list[locations.MemberLocation]:
    if args.members_csv:
        return locations.read_members_csv(Path(args.members_csv))

    sheet_id = args.sheet_id or os.environ.get("GOOGLE_SHEET_ID")
    if args.sheet_url:
        sheet_id = parse_sheet_id(args.sheet_url)
    if not sheet_id:
        raise SystemExit("Provide --sheet-url, --sheet-id, --members-csv, or GOOGLE_SHEET_ID.")

    sheet_name = args.sheet_name or os.environ.get("GOOGLE_SHEET_NAME", "Form Responses 1")
    try:
        return locations.read_sheet_members(sheet_id, sheet_name)
    except RuntimeError as exc:
        raise SystemExit(
            f"{exc}\n"
            "Google Sheetを公開CSVとして読めません。共有設定を「リンクを知っている全員が閲覧可」にするか、"
            "--members-csv にエクスポートCSVを渡してください。"
        ) from exc


def normalize_members(args: argparse.Namespace, members: list[locations.MemberLocation]) -> list[dict[str, Any]]:
    prefectures = locations.read_prefectures(Path(args.prefectures))
    aliases = locations.read_aliases(Path(args.aliases))
    overrides = locations.read_overrides(Path(args.overrides))
    normalized = [
        locations.normalize_location(
            member,
            prefectures,
            aliases,
            Path(args.cache_dir),
            not args.no_geolonia,
        )
        for member in members
    ]
    rows = [row.__dict__ for row in normalized]
    locations.apply_member_overrides(rows, overrides)
    locations.apply_display_offsets(rows)
    locations.apply_member_overrides(rows, overrides)
    return rows


def ensure_unique(rows: list[dict[str, Any]], key: str, label: str) -> None:
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for index, row in enumerate(rows, start=1):
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        if value in seen:
            duplicates.append(value)
        seen[value] = index
    if duplicates:
        joined = ", ".join(sorted(set(duplicates)))
        raise SystemExit(f"Duplicate {label} values are not safe to sync: {joined}")


def supabase_request(
    supabase_url: str,
    service_role_key: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
) -> Any:
    data = None
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"

    req = Request(
        f"{supabase_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body.decode("utf-8")) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase error {exc.code} {method} {path}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase request failed {method} {path}: {exc}") from exc


def fetch_existing_members(supabase_url: str, service_role_key: str) -> dict[str, dict[str, Any]]:
    select = ",".join(("id", "nickname", *SYNC_FIELDS, "avatar_path", "avatar_hash"))
    rows = supabase_request(
        supabase_url,
        service_role_key,
        f"/rest/v1/member_locations?select={select}&limit=10000",
    )
    rows = list(rows or [])
    ensure_unique(rows, "nickname", "Supabase nickname")
    return {str(row["nickname"]): row for row in rows if row.get("nickname")}


def values_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, float) or isinstance(right, float):
        try:
            return round(float(left), 6) == round(float(right), 6)
        except (TypeError, ValueError):
            return False
    return left == right


def row_changed(member: dict[str, Any], existing: dict[str, Any]) -> bool:
    return any(not values_equal(member.get(field), existing.get(field)) for field in CHANGE_FIELDS)


def build_member_payload(member: dict[str, Any], avatar: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        "nickname": member["nickname"],
        "location_text": member["location_text"],
        "prefecture": member.get("prefecture"),
        "municipality_optional": member.get("municipality_optional"),
        "location_level": member["location_level"],
        "lat": member.get("lat"),
        "lng": member.get("lng"),
        "map_lat": member.get("map_lat"),
        "map_lng": member.get("map_lng"),
        "geocode_source": member["geocode_source"],
    }
    if avatar:
        payload["avatar_path"] = avatar.get("avatar_path")
        payload["avatar_hash"] = avatar.get("avatar_hash")
    return payload


def match_and_upload_avatars(
    args: argparse.Namespace,
    members: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    if not members:
        return {}, {"matched": [], "unmatched": [], "duplicate_matches": []}

    sheet_members = [
        avatars.SheetMember(
            row_number=int(member["sheet_row"]),
            nickname=str(member["nickname"]),
            location_text=str(member["location_text"]),
        )
        for member in members
    ]
    name_map = avatars.read_name_map(Path(args.name_map) if args.name_map else None)
    discord_members = avatars.list_discord_members(
        require_env("DISCORD_BOT_TOKEN"),
        require_env("DISCORD_GUILD_ID"),
        args.include_bots,
    )
    match_report = avatars.match_members(
        sheet_members,
        discord_members,
        include_discord_user_id=False,
        name_map=name_map,
    )

    uploaded_by_row: dict[int, dict[str, Any]] = {}
    for match in match_report["matched"]:
        upload = avatar_uploads.process_member(
            match,
            supabase_url=require_env("SUPABASE_URL"),
            service_role_key=require_env("SUPABASE_SERVICE_ROLE_KEY"),
            bucket=args.bucket,
            dry_run=args.dry_run,
            max_bytes=args.max_avatar_bytes,
        )
        uploaded_by_row[upload.sheet_row] = asdict(upload)

    return uploaded_by_row, match_report


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the Google Form response sheet and sync only new/changed members to Supabase."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--sheet-url")
    parser.add_argument("--sheet-id")
    parser.add_argument("--sheet-name")
    parser.add_argument("--members-csv")
    parser.add_argument("--prefectures", default="config/prefecture_centroids.csv")
    parser.add_argument("--aliases", default="config/location_aliases.csv")
    parser.add_argument("--overrides", default="config/member_location_overrides.csv")
    parser.add_argument("--cache-dir", default="tmp/geolonia_cache")
    parser.add_argument("--name-map", default="config/member_discord_name_map.csv")
    parser.add_argument("--bucket", default=avatar_uploads.DEFAULT_BUCKET)
    parser.add_argument("--max-avatar-bytes", type=int, default=avatar_uploads.MAX_AVATAR_BYTES)
    parser.add_argument("--include-bots", action="store_true")
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--refresh-avatars", action="store_true")
    parser.add_argument("--no-geolonia", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="tmp/member_location_sync_report.json")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    source_members = read_source_members(args)
    normalized = normalize_members(args, source_members)
    ensure_unique(normalized, "nickname", "sheet nickname")

    ready = [row for row in normalized if not row["needs_review"]]
    needs_review = [row for row in normalized if row["needs_review"]]

    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    existing = fetch_existing_members(supabase_url, service_role_key)

    candidates: list[dict[str, Any]] = []
    actions: dict[str, str] = {}
    skipped_changed: list[dict[str, Any]] = []
    for member in ready:
        nickname = str(member["nickname"])
        current = existing.get(nickname)
        if current is None:
            candidates.append(member)
            actions[nickname] = "insert"
            continue
        if row_changed(member, current):
            if args.update_existing:
                candidates.append(member)
                actions[nickname] = "update"
            else:
                skipped_changed.append(
                    {
                        "nickname": nickname,
                        "current_location_text": current.get("location_text"),
                        "incoming_location_text": member.get("location_text"),
                    }
                )
            continue
        if args.refresh_avatars:
            candidates.append(member)
            actions[nickname] = "update"

    uploaded_by_row, match_report = match_and_upload_avatars(args, candidates)

    results: list[dict[str, Any]] = []
    for member in candidates:
        nickname = str(member["nickname"])
        current = existing.get(nickname)
        avatar = uploaded_by_row.get(int(member["sheet_row"]))
        if avatar is None and current:
            avatar = {
                "avatar_path": current.get("avatar_path"),
                "avatar_hash": current.get("avatar_hash"),
            }
        payload = build_member_payload(member, avatar)
        if args.dry_run:
            results.append({"nickname": nickname, "action": actions[nickname], "payload": payload})
            continue

        if current:
            path = f"/rest/v1/member_locations?nickname=eq.{quote(nickname)}"
            response = supabase_request(supabase_url, service_role_key, path, method="PATCH", payload=payload)
        else:
            response = supabase_request(supabase_url, service_role_key, "/rest/v1/member_locations", method="POST", payload=payload)
        results.append({"nickname": nickname, "action": actions[nickname], "response": response})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "summary": {
            "sheet_members": len(source_members),
            "ready": len(ready),
            "needs_review": len(needs_review),
            "existing": len(existing),
            "candidates": len(candidates),
            "insert": sum(1 for action in actions.values() if action == "insert"),
            "update": sum(1 for action in actions.values() if action == "update"),
            "avatar_matched": len(match_report.get("matched") or []),
            "avatar_unmatched": len(match_report.get("unmatched") or []),
            "skipped_changed": len(skipped_changed),
        },
        "needs_review": needs_review,
        "skipped_changed": skipped_changed,
        "avatar_unmatched": match_report.get("unmatched") or [],
        "avatar_duplicate_matches": match_report.get("duplicate_matches") or [],
        "results": results,
    }
    write_report(Path(args.report), report)

    summary = report["summary"]
    print(
        "Synced {candidates} candidates ({insert} insert, {update} update, {avatar_unmatched} avatar unmatched).".format(
            **summary
        )
    )
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
