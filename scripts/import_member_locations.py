#!/usr/bin/env python3
"""Import normalized member locations (with avatar paths) into Supabase."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def load_env(env_file: str = ".env") -> None:
    for line in Path(env_file).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def upsert_members(supabase_url: str, service_role_key: str, rows: list[dict]) -> None:
    url = f"{supabase_url.rstrip('/')}/rest/v1/member_locations"
    payload = json.dumps(rows).encode("utf-8")
    req = Request(
        url,
        data=payload,
        method="POST",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )
    try:
        with urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"挿入完了: {len(result)} 件")
    except HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Supabase error {e.code}: {body}") from e


def main() -> None:
    load_env()
    supabase_url = os.environ["SUPABASE_URL"]
    service_role_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    with open("tmp/member_locations_normalized.json") as f:
        members = {m["sheet_row"]: m for m in json.load(f)["members"]}

    with open("tmp/member_avatar_storage_paths.json") as f:
        avatars = {a["sheet_row"]: a for a in json.load(f)["avatars"]}

    rows = []
    for sheet_row, member in members.items():
        avatar = avatars.get(sheet_row, {})
        rows.append({
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
            "avatar_path": avatar.get("avatar_path"),
            "avatar_hash": avatar.get("avatar_hash"),
        })

    print(f"投入対象: {len(rows)} 件")
    upsert_members(supabase_url, service_role_key, rows)


if __name__ == "__main__":
    main()
