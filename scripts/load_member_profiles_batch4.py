#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the fourth tag-display batch (2 members).

Same upsert pattern as load_member_profiles.py / load_member_profiles_batch2.py / batch3.
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


MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "トマト🍅": [],
    "うつきゆき": [{"label": "note", "url": "https://note.com/noter_lab"}],
}

# category is one of: investment_style, fire_status, mbti, skill, interest
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "トマト🍅": {
        "investment_style": ["株式", "投信", "債券", "不動産"],
        "fire_status": ["FIRE済"],
        "mbti": [],
        "skill": ["資産管理法人運営"],
        "interest": ["資格取得"],
    },
    "うつきゆき": {
        "investment_style": ["米国インデックス", "高配当株投資（日本）", "仮想通貨"],
        "fire_status": ["コーストFIRE"],
        "mbti": [],
        "skill": ["アフィリエイト", "note執筆"],
        "interest": ["漫画"],
    },
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
    parser = argparse.ArgumentParser(description="Seed batch 4 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--self-intros", default="tmp/tag_display_self_intros_batch4.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    self_intros = json.loads(Path(args.self_intros).read_text(encoding="utf-8"))
    self_intro_by_nickname = {entry["nickname"]: entry for entry in self_intros}

    profiles: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []

    for nickname, categories in MEMBER_TAGS.items():
        intro = self_intro_by_nickname.get(nickname)
        if not intro or not intro.get("found"):
            raise SystemExit(f"No self-intro found for {nickname}")

        profiles.append(
            {
                "nickname": nickname,
                "avatar_url": intro.get("avatar_url"),
                "self_intro_text": intro.get("content") or None,
                "self_intro_url": intro.get("message_url"),
                "self_intro_posted_at": intro.get("posted_at"),
            }
        )

        for category, values in categories.items():
            for i, value in enumerate(values):
                tag_rows.append(
                    {"member_nickname": nickname, "category": category, "value": value, "sort_order": i}
                )

        for link in MEMBER_LINKS.get(nickname, []):
            link_rows.append(
                {"member_nickname": nickname, "label": link["label"], "url": link["url"]}
            )

    print(f"Prepared {len(profiles)} profiles, {len(tag_rows)} tags, {len(link_rows)} links.")

    if args.dry_run:
        print(json.dumps(
            {"profiles": profiles, "tags": tag_rows, "links": link_rows},
            ensure_ascii=False, indent=2,
        ))
        return 0

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/member_profiles?on_conflict=nickname",
        service_role_key,
        body=profiles,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted member_profiles.")

    supabase_request(
        "POST",
        f"{supabase_url}/rest/v1/member_tags?on_conflict=member_nickname,category,value",
        service_role_key,
        body=tag_rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )
    print("Upserted member_tags.")

    if link_rows:
        supabase_request(
            "POST",
            f"{supabase_url}/rest/v1/member_links?on_conflict=member_nickname,url",
            service_role_key,
            body=link_rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        print("Upserted member_links.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
