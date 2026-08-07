#!/usr/bin/env python3
"""Sync tag-display form nickname opt-ins into member_profiles."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


USER_AGENT = "fire-community-map-profile-form-sync/0.1"


@dataclass(frozen=True)
class FormMember:
    sheet_row: int
    nickname: str


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


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("　", " ")).strip()


PAREN_PATTERN = re.compile(r"[（(]([^）)]*)[）)]")


def fold_keys(nickname: str) -> set[str]:
    """Loose match keys for a nickname, to catch re-submissions with slightly
    different formatting (added parenthetical, case change, extra spaces)
    before treating them as a brand-new member.

    Example: "べる（Karin Bell）" and "べる" both produce the base key "べる".
    "echo(えこー)" and "えこー" both produce the paren-content key "えこー".
    """
    base = normalize_spaces(PAREN_PATTERN.sub("", nickname)).casefold()
    keys = {normalize_spaces(nickname).casefold()}
    if base:
        keys.add(base)
    for match in PAREN_PATTERN.finditer(nickname):
        inner = normalize_spaces(match.group(1)).casefold()
        if inner:
            keys.add(inner)
    return keys


def parse_sheet_id(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", sheet_url)
    if not match:
        raise SystemExit(f"Could not parse Google Sheet ID from URL: {sheet_url}")
    return match.group(1)


def http_get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed fetching {url}: {exc}") from exc


def read_members_csv(path: Path) -> list[FormMember]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows_to_members(rows)


def read_sheet_members(sheet_id: str, sheet_name: str) -> list[FormMember]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        f"{urlencode({'tqx': 'out:csv', 'sheet': sheet_name})}"
    )
    rows = list(csv.reader(http_get_text(url).splitlines()))
    return rows_to_members(rows)


def rows_to_members(rows: list[list[str]]) -> list[FormMember]:
    members: list[FormMember] = []
    for index, row in enumerate(rows[1:], start=2):
        nickname = normalize_spaces(row[1]) if len(row) > 1 else ""
        if nickname:
            members.append(FormMember(index, nickname))
    return members


def read_source_members(args: argparse.Namespace) -> list[FormMember]:
    if args.members_csv:
        return read_members_csv(Path(args.members_csv))

    sheet_id = args.sheet_id or os.environ.get("GOOGLE_SHEET_ID")
    if args.sheet_url:
        sheet_id = parse_sheet_id(args.sheet_url)
    if not sheet_id:
        raise SystemExit("Provide --sheet-url, --sheet-id, --members-csv, or GOOGLE_SHEET_ID.")

    sheet_name = args.sheet_name or os.environ.get("GOOGLE_SHEET_NAME", "Form Responses 1")
    try:
        return read_sheet_members(sheet_id, sheet_name)
    except RuntimeError as exc:
        raise SystemExit(
            f"{exc}\n"
            "Google Sheetを公開CSVとして読めません。非公開シートの場合は --members-csv を渡してください。"
        ) from exc


def dedupe_members_by_latest(members: list[FormMember]) -> tuple[list[FormMember], list[dict[str, Any]]]:
    latest_by_nickname: dict[str, FormMember] = {}
    duplicates_by_nickname: dict[str, list[FormMember]] = {}

    for member in members:
        previous = latest_by_nickname.get(member.nickname)
        if previous:
            duplicates_by_nickname.setdefault(member.nickname, [previous]).append(member)
        latest_by_nickname[member.nickname] = member

    duplicate_report = [
        {
            "nickname": nickname,
            "sheet_rows": [member.sheet_row for member in rows],
            "latest_sheet_row": latest_by_nickname[nickname].sheet_row,
        }
        for nickname, rows in sorted(duplicates_by_nickname.items())
    ]
    return list(latest_by_nickname.values()), duplicate_report


def supabase_request(
    supabase_url: str,
    service_role_key: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    prefer: str | None = None,
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
    if prefer:
        headers["Prefer"] = prefer

    request = Request(f"{supabase_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase error {exc.code} {method} {path}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase request failed {method} {path}: {exc}") from exc


def fetch_existing_profiles(supabase_url: str, service_role_key: str) -> set[str]:
    rows = supabase_request(
        supabase_url,
        service_role_key,
        "/rest/v1/member_profiles?select=nickname&limit=10000",
    )
    return {str(row["nickname"]) for row in rows or [] if row.get("nickname")}


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the tag-display form response sheet and add new nicknames to member_profiles."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--sheet-url")
    parser.add_argument("--sheet-id")
    parser.add_argument("--sheet-name")
    parser.add_argument("--members-csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="tmp/member_profile_form_sync_report.json")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    source_members = read_source_members(args)
    sync_members, duplicate_sheet_nicknames = dedupe_members_by_latest(source_members)

    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    existing = fetch_existing_profiles(supabase_url, service_role_key)

    existing_fold_index: dict[str, list[str]] = {}
    for nickname in existing:
        for key in fold_keys(nickname):
            existing_fold_index.setdefault(key, []).append(nickname)

    candidates: list[FormMember] = []
    skipped_existing = [member for member in sync_members if member.nickname in existing]
    possible_duplicates: list[dict[str, Any]] = []

    for member in sync_members:
        if member.nickname in existing:
            continue
        matches = sorted(
            {
                existing_nickname
                for key in fold_keys(member.nickname)
                for existing_nickname in existing_fold_index.get(key, [])
            }
        )
        if matches:
            possible_duplicates.append(
                {"sheet_row": member.sheet_row, "nickname": member.nickname, "likely_matches": matches}
            )
        else:
            candidates.append(member)

    payload = [{"nickname": member.nickname} for member in candidates]

    response = None
    if payload and not args.dry_run:
        response = supabase_request(
            supabase_url,
            service_role_key,
            "/rest/v1/member_profiles?on_conflict=nickname",
            method="POST",
            payload=payload,
            prefer="resolution=ignore-duplicates,return=representation",
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "summary": {
            "sheet_members": len(source_members),
            "sync_members": len(sync_members),
            "duplicate_sheet_nicknames": len(duplicate_sheet_nicknames),
            "existing": len(existing),
            "candidates": len(candidates),
            "insert": len(payload) if not args.dry_run else 0,
            "skipped_existing": len(skipped_existing),
            "possible_duplicates": len(possible_duplicates),
        },
        "duplicate_sheet_nicknames": duplicate_sheet_nicknames,
        "candidates": [{"sheet_row": member.sheet_row, "nickname": member.nickname} for member in candidates],
        "skipped_existing": [
            {"sheet_row": member.sheet_row, "nickname": member.nickname} for member in skipped_existing
        ],
        "possible_duplicates": possible_duplicates,
        "response": response,
    }
    write_report(Path(args.report), report)

    summary = report["summary"]
    print(
        "Synced {candidates} profile candidates ({insert} insert, {skipped_existing} skipped existing, "
        "{possible_duplicates} possible duplicates held back for review).".format(**summary)
    )
    if possible_duplicates:
        print("Possible duplicates (not inserted, needs manual review):")
        for entry in possible_duplicates:
            print(f"  - {entry['nickname']!r} looks like: {entry['likely_matches']}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
