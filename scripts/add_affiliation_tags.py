#!/usr/bin/env python3
"""Add 'affiliation' (所属活動・部活) tags to member_tags for members who
appear in the FIRE研究所 team-assignment chart and already have a directory
profile. People in the chart without a member_profiles row are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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


# nickname (as stored in member_profiles) -> list of affiliation values
AFFILIATION_TAGS: dict[str, list[str]] = {
    "ひつじ": ["FIRE1年目の教科書（仮）出版チーム", "新メンバー選考チーム", "ITチーム", "note運用チーム", "Discord運営チーム"],
    "モンチ": ["FIRE1年目の教科書（仮）出版チーム", "ITチーム", "X運用チーム", "文学フリマ大阪実行委員"],
    "みかん": [
        "FIRE1年目の教科書（仮）出版チーム", "新メンバー選考チーム", "YouTube運営チーム", "ITチーム",
        "ロゴコンテスト実行委員", "X運用チーム", "note運用チーム", "寺子屋企画チーム",
        "相談プロジェクト", "文学フリマ大阪実行委員", "会計チーム",
    ],
    "さとりーまん": ["新メンバー選考チーム", "YouTube運営チーム"],
    "にょろ": ["新メンバー選考チーム"],
    "カサドール": ["YouTube運営チーム"],
    "こーいち": ["YouTube運営チーム"],
    "ちゃん": ["YouTube運営チーム", "料理部"],
    "ちぃ": ["YouTube運営チーム"],
    "かず": ["ITチーム", "読書部", "スプラ部"],
    "soto": ["ITチーム"],
    "とみと": ["ロゴコンテスト実行委員", "料理部", "スナック"],
    "りぜ": ["X運用チーム"],
    "みなくさ": ["note運用チーム", "文学フリマ大阪実行委員"],
    "Nyupy": ["相談プロジェクト", "文学フリマ大阪実行委員"],
    "瑠璃": ["会計チーム"],
    "べる": ["料理部", "スプラ部"],
    "haru": ["読書部", "スプラ部"],
    "こはん": ["麻雀部"],
    "あきら": ["麻雀部"],
    "ほたて": ["麻雀部"],
    "もふりびと。": ["ロゴコンテスト実行委員", "麻雀部", "スプラ部", "スナック"],
    "うつきゆき": ["文学フリマ大阪実行委員"],
}


def supabase_request(
    method: str,
    url: str,
    service_role_key: str,
    body: Any = None,
    prefer: str | None = None,
) -> Any:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Insert affiliation tags into member_tags.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    tag_rows: list[dict[str, Any]] = []
    for nickname, values in AFFILIATION_TAGS.items():
        for value in values:
            tag_rows.append({"member_nickname": nickname, "category": "affiliation", "value": value})

    print(f"Prepared {len(tag_rows)} affiliation tag rows for {len(AFFILIATION_TAGS)} members.")

    if args.dry_run:
        print(json.dumps(tag_rows, ensure_ascii=False, indent=2))
        return 0

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/member_tags?on_conflict=member_nickname,category,value",
        service_role_key,
        body=tag_rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted affiliation tags into member_tags.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
