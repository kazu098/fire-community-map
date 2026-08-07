#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the twenty-third tag-display batch (1 member: ヒライム).

Same upsert pattern as load_member_profiles.py / batch2-22.
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


PROFILE = {
    "nickname": "ヒライム",
    "avatar_url": "https://cdn.discordapp.com/avatars/903652538832805898/bbea6797c5be10b64690a5ba55f33147.png?size=128",
    "self_intro_text": (
        "初めまして。ヒライムです。\n"
        "noteとXやってます︎︎👍\n"
        "\n"
        "仕事をサボりまくり、給料を奪い尽くす資本主義のアンチテーゼ、モンスター社員として君臨しています👾\n"
        "\n"
        "noteでは様々なセコ活・投資情報・サボりマインド等について、一方Xでは理系院卒なのにうだつの上がらない勤続年数20年の平社員が仕事をしないのに主任を目指すサクセスストーリーについて記載しています。\n"
        "\n"
        "FIREとしては、窓際FIREを目指しています。定年まで逃げ切り、会社に生涯賃金である被害総額3億円を叩きつけたいです。\n"
        "\n"
        "新参者ですが、宜しくお願いいたします🙇‍♀️"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1423997342474043442",
    "self_intro_posted_at": "2025-10-04T11:37:03.037000+00:00",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "ヒライム": [
        {"label": "note", "url": "https://note.com/hirariman"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "ヒライム": {
        "investment_style": [],
        "fire_status": ["窓際FIRE"],
        "mbti": [],
        "skill": [],
        "interest": ["セコ活"],
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
    parser = argparse.ArgumentParser(description="Seed batch 23 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    profiles = [PROFILE]
    tag_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []

    for nickname, categories in MEMBER_TAGS.items():
        for category, values in categories.items():
            for i, value in enumerate(values):
                tag_rows.append(
                    {"member_nickname": nickname, "category": category, "value": value, "sort_order": i}
                )

    for nickname, links in MEMBER_LINKS.items():
        for link in links:
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
