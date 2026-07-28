#!/usr/bin/env python3
"""Upsert curated community events into Supabase.

Reads tmp/community_events_curated.json. Event rows are intentionally curated
records, not a raw Discord log mirror: the UI is meant to help members find
upcoming events and help organizers review past events quickly.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_FIELDS = ("title", "starts_at", "format", "discord_message_id", "discord_permalink")
VALID_FORMATS = {"online", "offline", "hybrid", "unknown"}


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


def supabase_request(method: str, url: str, service_role_key: str, body: Any = None, prefer: str | None = None) -> Any:
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


def validate_datetime(value: str, field: str, title: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"Event {title!r} has invalid {field}: {value}") from exc
    if parsed.tzinfo is None:
        raise SystemExit(f"Event {title!r} has timezone-less {field}: {value}")


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit("tags must be a JSON array when provided.")
    return [str(tag).strip() for tag in value if str(tag).strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert curated community events into Supabase.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--curated", default="tmp/community_events_curated.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    curated = json.loads(Path(args.curated).read_text(encoding="utf-8"))
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")

    rows = []
    for entry in curated:
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise SystemExit(f"Event {entry.get('title', '?')!r} missing required fields: {missing}")
        if entry["format"] not in VALID_FORMATS:
            raise SystemExit(f"Event {entry['title']!r} has invalid format: {entry['format']}")
        validate_datetime(entry["starts_at"], "starts_at", entry["title"])
        if entry.get("ends_at"):
            validate_datetime(entry["ends_at"], "ends_at", entry["title"])
        if entry.get("cancelled_at"):
            validate_datetime(entry["cancelled_at"], "cancelled_at", entry["title"])

        rows.append(
            {
                "title": entry["title"],
                "tags": normalize_tags(entry.get("tags")),
                "starts_at": entry["starts_at"],
                "ends_at": entry.get("ends_at"),
                "format": entry["format"],
                "prefecture": entry.get("prefecture"),
                "location_label": entry.get("location_label"),
                "participant_count": entry.get("participant_count"),
                "participation_note": entry.get("participation_note"),
                "summary": entry.get("summary"),
                "highlights": entry.get("highlights"),
                "learnings": entry.get("learnings"),
                "discord_channel_name": entry.get("channel_name") or entry.get("discord_channel_name"),
                "discord_message_id": str(entry["discord_message_id"]) if entry.get("discord_message_id") else None,
                "discord_permalink": entry.get("discord_permalink"),
                "cancelled_at": entry.get("cancelled_at"),
            }
        )

    print(f"Prepared {len(rows)} community_events rows to upsert.")
    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if rows:
        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/community_events?on_conflict=discord_message_id",
            service_role_key,
            body=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print("Upserted community_events.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
