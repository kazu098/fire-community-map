#!/usr/bin/env python3
"""Normalize free-form member locations for map ingestion."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


USER_AGENT = "fire-community-map-location-normalizer/0.1"
GEOLONIA_BASE = "https://geolonia.github.io/japanese-addresses/api/ja"
PREFECTURE_PATTERN = re.compile(
    r"^(北海道|東京都|京都府|大阪府|.{2,3}県)(.*)$"
)
WARD_IN_CITY_PATTERN = re.compile(r"^(.+市.+区)")
DISTRICT_TOWN_PATTERN = re.compile(r"^(.+郡.+[町村])")
CITY_PATTERN = re.compile(r"^(.+市)")
WARD_TOWN_VILLAGE_PATTERN = re.compile(r"^(.+[区町村])")


@dataclass(frozen=True)
class MemberLocation:
    sheet_row: int
    nickname: str
    location_text: str


@dataclass(frozen=True)
class NormalizedLocation:
    sheet_row: int
    nickname: str
    location_text: str
    prefecture: str | None
    municipality_optional: str | None
    location_level: str
    lat: float | None
    lng: float | None
    geocode_source: str
    needs_review: bool
    review_reason: str | None


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


def http_get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8-sig")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed fetching {url}: {exc}") from exc


def read_members_csv(path: Path) -> list[MemberLocation]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows_to_members(rows)


def read_sheet_members(sheet_id: str, sheet_name: str) -> list[MemberLocation]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        f"{urlencode({'tqx': 'out:csv', 'sheet': sheet_name})}"
    )
    rows = list(csv.reader(http_get_text(url).splitlines()))
    return rows_to_members(rows)


def rows_to_members(rows: list[list[str]]) -> list[MemberLocation]:
    members: list[MemberLocation] = []
    for index, row in enumerate(rows[1:], start=2):
        nickname = row[1].strip() if len(row) > 1 else ""
        location_text = normalize_spaces(row[3]) if len(row) > 3 else ""
        if not nickname:
            continue
        members.append(MemberLocation(index, nickname, location_text))
    return members


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("　", " ")).strip()


def read_prefectures(path: Path) -> dict[str, tuple[float, float]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            row["prefecture"].strip(): (float(row["lat"]), float(row["lng"]))
            for row in rows
        }


def read_aliases(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            normalize_spaces(row["input"]): row
            for row in csv.DictReader(handle)
            if row.get("input")
        }


def normalize_location(
    member: MemberLocation,
    prefectures: dict[str, tuple[float, float]],
    aliases: dict[str, dict[str, str]],
    cache_dir: Path,
    use_geolonia: bool,
) -> NormalizedLocation:
    location_text = normalize_spaces(member.location_text)
    if not location_text:
        return make_result(member, None, None, "unknown", None, None, "empty", True, "location_text is empty")

    alias = aliases.get(location_text)
    if alias:
        return result_from_alias(member, alias)

    match = PREFECTURE_PATTERN.match(location_text)
    if not match:
        return make_result(
            member,
            None,
            None,
            "unknown",
            None,
            None,
            "unmatched",
            True,
            "都道府県を判定できません",
        )

    prefecture = match.group(1)
    rest = normalize_spaces(match.group(2))
    if prefecture not in prefectures:
        return make_result(
            member,
            prefecture,
            None,
            "unknown",
            None,
            None,
            "unmatched",
            True,
            "都道府県代表座標がありません",
        )

    if not rest:
        lat, lng = prefectures[prefecture]
        return make_result(
            member,
            prefecture,
            None,
            "prefecture",
            lat,
            lng,
            "prefecture_static",
            False,
            None,
        )

    municipality = extract_municipality(rest)
    if not municipality:
        return make_result(
            member,
            prefecture,
            rest,
            "area",
            None,
            None,
            "manual_review",
            True,
            "市区町村として判定できない都道府県内エリアです",
        )

    if not use_geolonia:
        lat, lng = prefectures[prefecture]
        return make_result(
            member,
            prefecture,
            municipality,
            "municipality",
            lat,
            lng,
            "prefecture_static_fallback",
            True,
            "Geolonia未使用のため都道府県代表点で仮置き",
        )

    try:
        lat, lng = geocode_municipality(prefecture, municipality, cache_dir)
        return make_result(
            member,
            prefecture,
            municipality,
            "municipality",
            lat,
            lng,
            "geolonia",
            False,
            None,
        )
    except RuntimeError as exc:
        lat, lng = prefectures[prefecture]
        return make_result(
            member,
            prefecture,
            municipality,
            "municipality",
            lat,
            lng,
            "prefecture_static_fallback",
            True,
            str(exc),
        )


def result_from_alias(member: MemberLocation, alias: dict[str, str]) -> NormalizedLocation:
    lat = parse_float(alias.get("lat"))
    lng = parse_float(alias.get("lng"))
    needs_review = not (lat is not None and lng is not None)
    note = alias.get("note") or None
    return make_result(
        member,
        empty_to_none(alias.get("prefecture")),
        empty_to_none(alias.get("municipality_optional")),
        alias.get("location_level") or "unknown",
        lat,
        lng,
        alias.get("geocode_source") or "manual_alias",
        needs_review,
        note if needs_review else None,
    )


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def extract_municipality(value: str) -> str | None:
    value = normalize_spaces(value)
    for pattern in (
        WARD_IN_CITY_PATTERN,
        DISTRICT_TOWN_PATTERN,
        CITY_PATTERN,
        WARD_TOWN_VILLAGE_PATTERN,
    ):
        match = pattern.match(value)
        if match:
            return match.group(1)
    return None


def geocode_municipality(prefecture: str, municipality: str, cache_dir: Path) -> tuple[float, float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{prefecture}_{municipality}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        url = f"{GEOLONIA_BASE}/{quote(prefecture)}/{quote(municipality)}.json"
        payload = json.loads(http_get_text(url))
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
    return round(lat, 6), round(lng, 6)


def make_result(
    member: MemberLocation,
    prefecture: str | None,
    municipality_optional: str | None,
    location_level: str,
    lat: float | None,
    lng: float | None,
    geocode_source: str,
    needs_review: bool,
    review_reason: str | None,
) -> NormalizedLocation:
    return NormalizedLocation(
        sheet_row=member.sheet_row,
        nickname=member.nickname,
        location_text=member.location_text,
        prefecture=prefecture,
        municipality_optional=municipality_optional,
        location_level=location_level,
        lat=lat,
        lng=lng,
        geocode_source=geocode_source,
        needs_review=needs_review,
        review_reason=review_reason,
    )


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(rows),
            "ready": sum(1 for row in rows if not row["needs_review"]),
            "needs_review": sum(1 for row in rows if row["needs_review"]),
        },
        "members": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "sheet_row",
        "nickname",
        "location_text",
        "prefecture",
        "municipality_optional",
        "location_level",
        "lat",
        "lng",
        "geocode_source",
        "needs_review",
        "review_reason",
        "map_lat",
        "map_lng",
        "coordinate_group_key",
        "coordinate_group_index",
        "coordinate_group_size",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Google Form member locations for map ingestion."
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--members-csv", default=os.environ.get("MEMBER_SOURCE_CSV"))
    parser.add_argument("--prefectures", default="config/prefecture_centroids.csv")
    parser.add_argument("--aliases", default="config/location_aliases.csv")
    parser.add_argument("--cache-dir", default="tmp/geolonia_cache")
    parser.add_argument("--output-json", default="tmp/member_locations_normalized.json")
    parser.add_argument("--output-csv", default="tmp/member_locations_normalized.csv")
    parser.add_argument("--no-geolonia", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))

    if args.members_csv:
        members = read_members_csv(Path(args.members_csv))
    else:
        sheet_id = require_env("GOOGLE_SHEET_ID")
        sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Form Responses 1")
        members = read_sheet_members(sheet_id, sheet_name)

    prefectures = read_prefectures(Path(args.prefectures))
    aliases = read_aliases(Path(args.aliases))
    normalized = [
        normalize_location(
            member,
            prefectures,
            aliases,
            Path(args.cache_dir),
            not args.no_geolonia,
        )
        for member in members
    ]
    rows = [row.__dict__ for row in normalized]
    apply_display_offsets(rows)

    write_json(Path(args.output_json), rows)
    write_csv(Path(args.output_csv), rows)

    ready = sum(1 for row in rows if not row["needs_review"])
    needs_review = len(rows) - ready
    print(f"Normalized {len(rows)} member locations ({ready} ready, {needs_review} need review).")
    print(f"Wrote {args.output_json}")
    print(f"Wrote {args.output_csv}")
    return 0


def apply_display_offsets(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        lat = row.get("lat")
        lng = row.get("lng")
        if lat is None or lng is None:
            row["map_lat"] = None
            row["map_lng"] = None
            row["coordinate_group_key"] = None
            row["coordinate_group_index"] = None
            row["coordinate_group_size"] = 0
            continue
        key = f"{float(lat):.5f},{float(lng):.5f}"
        groups.setdefault(key, []).append(row)

    GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))  # ~137.508°

    for key, group in groups.items():
        group.sort(key=lambda row: (row["nickname"], row["sheet_row"]))
        size = len(group)
        for index, row in enumerate(group):
            row["coordinate_group_key"] = key
            row["coordinate_group_index"] = index
            row["coordinate_group_size"] = size
            if size == 1:
                row["map_lat"] = row["lat"]
                row["map_lng"] = row["lng"]
                continue

            lat = float(row["lat"])
            lng = float(row["lng"])

            level = row.get("location_level", "unknown")
            if level == "prefecture":
                max_radius_km = 20.0
            elif level in ("area", "region", "multi_region"):
                max_radius_km = 10.0
            else:
                max_radius_km = 2.0

            # ファイロタクシス配置（ひまわり型）: 円より自然なばらけ方
            r = max_radius_km * math.sqrt((index + 0.5) / size)
            angle = GOLDEN_ANGLE * index
            row["map_lat"] = round(lat + (r / 111.0) * math.sin(angle), 6)
            row["map_lng"] = round(
                lng + (r / (111.0 * max(math.cos(math.radians(lat)), 0.2))) * math.cos(angle),
                6,
            )


if __name__ == "__main__":
    raise SystemExit(main())
