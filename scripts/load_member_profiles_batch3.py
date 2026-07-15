#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the third tag-display batch (5 members).

Same upsert pattern as load_member_profiles.py / load_member_profiles_batch2.py.
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
    "りぜ": [{"label": "note", "url": "https://note.com/ridetozero_jp"}],
    "白瀬": [],
    "こーいち": [],
    "Yuji": [],
    "hakunoie（はく）": [],
}

# category is one of: investment_style, fire_status, mbti, skill, interest
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "りぜ": {
        "investment_style": ["NISA", "iDeCo", "インデックス投資"],
        "fire_status": ["派遣サイドFIRE"],
        "mbti": [],
        "skill": ["外資マーケティング"],
        "interest": ["自転車旅行", "キャンプ", "note"],
    },
    "白瀬": {
        "investment_style": ["インデックス投資", "個別株"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["INFP"],
        "skill": [],
        "interest": ["ゲーム", "漫画", "音楽鑑賞", "鳥"],
    },
    "こーいち": {
        "investment_style": ["インデックス投資", "日本株", "米国株", "企業型DC", "NISA"],
        "fire_status": ["会社員"],
        "mbti": [],
        "skill": ["PMO(IT系)"],
        "interest": ["ランニング", "ヨガ", "サーフィン"],
    },
    "Yuji": {
        "investment_style": ["ドル建て社債", "持株会", "企業型DC", "インド定期預金"],
        "fire_status": ["コーストFIRE"],
        "mbti": ["INTJ-T"],
        "skill": ["海外現地法人CMO"],
        "interest": ["ジャズ", "アート鑑賞", "ハイキング", "俳句"],
    },
    "hakunoie（はく）": {
        "investment_style": ["インデックス投資", "個人向け国債"],
        "fire_status": ["FIRE済"],
        "mbti": ["INTJ-T"],
        "skill": [],
        "interest": ["旅行", "アウトドア(キャンプ/スキー)", "読書", "二拠点生活"],
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
    parser = argparse.ArgumentParser(description="Seed batch 3 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--self-intros", default="tmp/tag_display_self_intros_batch3.json")
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
            for value in values:
                tag_rows.append(
                    {"member_nickname": nickname, "category": category, "value": value}
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
