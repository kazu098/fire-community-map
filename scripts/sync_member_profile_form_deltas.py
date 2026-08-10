#!/usr/bin/env python3
"""Sync tag-display form responses into public member profiles."""

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
    tags: dict[str, list[str]]
    links: list[dict[str, str]]
    external_self_intro_text: str | None = None
    location_text: str | None = None


CATEGORY_HEADERS = {
    "investment_style": ("投資スタイル", "投資", "資産運用"),
    "fire_status": ("FIREステータス", "FIRE状況", "FIRE"),
    "mbti": ("MBTI",),
    "skill": ("スキル", "得意"),
    "consultation": ("相談できること", "相談"),
    "interest": ("趣味", "興味", "関心"),
    "affiliation": ("所属活動", "部活", "所属"),
}
NICKNAME_HEADERS = ("ニックネーム", "nickname", "表示名")
INTRO_HEADERS = ("外部向け自己紹介", "自己紹介", "紹介文", "プロフィール")
LOCATION_HEADERS = ("居住地", "お住まい", "住所", "都道府県")
LINK_HEADERS = ("リンク", "URL", "note", "YouTube", "ブログ", "SNS", "X（Twitter）", "Twitter")


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


def normalize_header(value: str) -> str:
    return normalize_spaces(value).casefold()


def header_matches(header: str, needles: tuple[str, ...]) -> bool:
    normalized = normalize_header(header)
    return any(normalize_header(needle) in normalized for needle in needles)


def find_first_column(headers: list[str], aliases: tuple[str, ...], *, fallback: int | None = None) -> int | None:
    for index, header in enumerate(headers):
        if header_matches(header, aliases):
            return index
    return fallback if fallback is not None and fallback < len(headers) else None


def split_multi_value(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    parts = re.split(r"[\n\r,、;；/／]+", text)
    values: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = normalize_spaces(part)
        if not item or item in seen:
            continue
        values.append(item)
        seen.add(item)
    return values


def looks_like_url(value: str) -> bool:
    return bool(re.match(r"https?://", value.strip()))


def link_label_from_header(header: str, index: int) -> str:
    text = normalize_spaces(header)
    lowered = text.casefold()
    if "youtube" in lowered:
        return "YouTube"
    if "note" in lowered:
        return "note"
    if "ブログ" in text or "blog" in lowered:
        return "ブログ"
    if "twitter" in lowered or "x（twitter" in lowered:
        return "X"
    return "リンク" if index == 0 else f"リンク{index + 1}"


def cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return normalize_spaces(row[index])


def raw_cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


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
    if not rows:
        return []

    headers = rows[0]
    nickname_col = find_first_column(headers, NICKNAME_HEADERS, fallback=1)
    intro_col = find_first_column(headers, INTRO_HEADERS)
    location_col = find_first_column(headers, LOCATION_HEADERS)
    category_columns: dict[str, list[int]] = {}
    assigned_category_columns: set[int] = set()
    for category, aliases in CATEGORY_HEADERS.items():
        columns = []
        for index, header in enumerate(headers):
            if index == nickname_col or index in assigned_category_columns:
                continue
            if header_matches(header, aliases):
                columns.append(index)
                assigned_category_columns.add(index)
        category_columns[category] = columns
    link_columns = [
        index
        for index, header in enumerate(headers)
        if header_matches(header, LINK_HEADERS) and index not in {nickname_col, intro_col, location_col}
    ]

    members: list[FormMember] = []
    for index, row in enumerate(rows[1:], start=2):
        nickname = cell(row, nickname_col)
        if nickname:
            tags = {
                category: [
                    value
                    for column in columns
                    for value in split_multi_value(raw_cell(row, column))
                    if value
                ]
                for category, columns in category_columns.items()
            }
            tags = {category: values for category, values in tags.items() if values}

            links: list[dict[str, str]] = []
            for link_index, column in enumerate(link_columns):
                url = cell(row, column)
                if looks_like_url(url):
                    links.append({"label": link_label_from_header(headers[column], link_index), "url": url})

            members.append(
                FormMember(
                    index,
                    nickname,
                    tags=tags,
                    links=links,
                    external_self_intro_text=cell(row, intro_col) or None,
                    location_text=cell(row, location_col) or None,
                )
            )
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


def fetch_existing_profiles(supabase_url: str, service_role_key: str) -> dict[str, dict[str, Any]]:
    rows = supabase_request(
        supabase_url,
        service_role_key,
        "/rest/v1/member_profiles?select=nickname,avatar_url,self_intro_text,external_self_intro_text,location_text,nickname_public,avatar_public,self_intro_public,location_public,links_public&limit=10000",
    )
    return {str(row["nickname"]): row for row in rows or [] if row.get("nickname")}


def build_profile_payload(member: FormMember, existing_profile: dict[str, Any] | None) -> dict[str, Any]:
    external_intro = member.external_self_intro_text
    if external_intro is None and existing_profile:
        external_intro = existing_profile.get("external_self_intro_text") or existing_profile.get("self_intro_text")

    location_text = member.location_text
    if location_text is None and existing_profile:
        location_text = existing_profile.get("location_text")

    avatar_url = existing_profile.get("avatar_url") if existing_profile else None

    return {
        "nickname": member.nickname,
        "external_self_intro_text": external_intro,
        "location_text": location_text,
        "nickname_public": True,
        "avatar_public": bool(avatar_url),
        "self_intro_public": bool(external_intro),
        "location_public": bool(location_text),
        "links_public": bool(member.links) or bool(existing_profile and existing_profile.get("links_public")),
    }


def tag_rows_for_member(member: FormMember) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category, values in member.tags.items():
        for sort_order, value in enumerate(values):
            rows.append(
                {
                    "member_nickname": member.nickname,
                    "category": category,
                    "value": value,
                    "sort_order": sort_order,
                }
            )
    return rows


def sync_tags(
    supabase_url: str,
    service_role_key: str,
    member: FormMember,
    *,
    dry_run: bool,
) -> int:
    tag_rows = tag_rows_for_member(member)
    if not tag_rows or dry_run:
        return len(tag_rows)
    categories = sorted(member.tags)
    query = (
        f"member_nickname=eq.{quote(member.nickname, safe='')}"
        f"&category=in.({','.join(quote(category, safe='') for category in categories)})"
    )
    supabase_request(supabase_url, service_role_key, f"/rest/v1/member_tags?{query}", method="DELETE")
    supabase_request(
        supabase_url,
        service_role_key,
        "/rest/v1/member_tags?on_conflict=member_nickname,category,value",
        method="POST",
        payload=tag_rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return len(tag_rows)


def sync_links(
    supabase_url: str,
    service_role_key: str,
    member: FormMember,
    *,
    dry_run: bool,
) -> int:
    if not member.links or dry_run:
        return len(member.links)
    payload = [
        {"member_nickname": member.nickname, "label": link["label"], "url": link["url"]}
        for link in member.links
    ]
    supabase_request(
        supabase_url,
        service_role_key,
        "/rest/v1/member_links?on_conflict=member_nickname,url",
        method="POST",
        payload=payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return len(payload)


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the tag-display form response sheet and publish member profile fields."
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
    existing_profiles = fetch_existing_profiles(supabase_url, service_role_key)
    existing = set(existing_profiles)

    existing_fold_index: dict[str, list[str]] = {}
    for nickname in existing:
        for key in fold_keys(nickname):
            existing_fold_index.setdefault(key, []).append(nickname)

    candidates: list[FormMember] = []
    exact_existing = [member for member in sync_members if member.nickname in existing]
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

    syncable_members = [*exact_existing, *candidates]
    payload = [
        build_profile_payload(member, existing_profiles.get(member.nickname))
        for member in syncable_members
    ]

    response = None
    if payload and not args.dry_run:
        response = supabase_request(
            supabase_url,
            service_role_key,
            "/rest/v1/member_profiles?on_conflict=nickname",
            method="POST",
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )

    tags_synced = 0
    links_synced = 0
    for member in syncable_members:
        tags_synced += sync_tags(supabase_url, service_role_key, member, dry_run=args.dry_run)
        links_synced += sync_links(supabase_url, service_role_key, member, dry_run=args.dry_run)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "summary": {
            "sheet_members": len(source_members),
            "sync_members": len(sync_members),
            "duplicate_sheet_nicknames": len(duplicate_sheet_nicknames),
            "existing": len(existing),
            "candidates": len(candidates),
            "profiles_upserted": len(payload) if not args.dry_run else 0,
            "existing_profiles_updated": len(exact_existing) if not args.dry_run else 0,
            "insert": len(candidates) if not args.dry_run else 0,
            "tags_synced": tags_synced,
            "links_synced": links_synced,
            "possible_duplicates": len(possible_duplicates),
        },
        "duplicate_sheet_nicknames": duplicate_sheet_nicknames,
        "candidates": [
            {
                "sheet_row": member.sheet_row,
                "nickname": member.nickname,
                "tags": member.tags,
                "links": member.links,
                "external_self_intro_text": member.external_self_intro_text,
                "location_text": member.location_text,
            }
            for member in candidates
        ],
        "updated_existing": [
            {
                "sheet_row": member.sheet_row,
                "nickname": member.nickname,
                "tags": member.tags,
                "links": member.links,
                "external_self_intro_text": member.external_self_intro_text,
                "location_text": member.location_text,
            }
            for member in exact_existing
        ],
        "possible_duplicates": possible_duplicates,
        "response": response,
    }
    write_report(Path(args.report), report)

    summary = report["summary"]
    print(
        "Synced {profiles_upserted} profiles ({insert} new, {existing_profiles_updated} existing, "
        "{tags_synced} tags, {links_synced} links, {possible_duplicates} possible duplicates held back for review)."
        .format(**summary)
    )
    if possible_duplicates:
        print("Possible duplicates (not inserted, needs manual review):")
        for entry in possible_duplicates:
            print(f"  - {entry['nickname']!r} looks like: {entry['likely_matches']}")
    print(f"Wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
