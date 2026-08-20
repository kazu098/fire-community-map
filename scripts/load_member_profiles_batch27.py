#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the twenty-seventh tag-display batch (1 member: あおい).

The tag-display form response only contained the opt-in nickname. Profile
content below is curated from the member's Discord self-introduction post
and cross-referenced against the master profile spreadsheet.
Same upsert pattern as load_member_profiles.py / batch2-26.
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


SELF_INTRO_TEXT = (
    "浮雲さんのnoteでコミュニティを知り、応募しました！\n"
    "当選してとっても嬉しいです！\n"
    "（三連休ドタバタとしていた為、ご挨拶遅れました🙇） \n"
    "\n"
    "【ニックネーム】\n"
    "あおい\n"
    "\n"
    "【属性】\n"
    "夫との2人暮らし\n"
    "\n"
    "【年齢・居住地】\n"
    "・30代後半・関東\n"
    "・関西に移住する予定です\n"
    "\n"
    "【現在の仕事・収入源】\n"
    "今年会社員を卒業し、現在は元の会社で週1 ＋ AI関連でゆるく働きながら、今後の暮らしを模索してます。\n"
    "\n"
    "【投資・資産運用の状況】\n"
    "インデックス投資、個別株、ゴールドなど\n"
    "\n"
    "【無職になったら】\n"
    "・安い古い家を買ってセルフリノベをしたい（内装の職業訓練に行こうと思ってます）\n"
    "・kindle出版なのか個人アプリ開発なのか、儲けをあまり考えず、心の動くままに制作をして、自分＋α誰と楽しめるものを作りたい\n"
    "・将来のことをあんまり考えず、穏やかに楽しく暮らしたい\n"
    "\n"
    "【一言】\n"
    "周囲がバリバリと働いている中、不安になることもあるので、このコミュニティでは皆さまとリアルな悩みや楽しみの共有をしながら、自分らしいライフスタイルを作り上げていきたいです。\n"
    "マイペースにnoteもやっているので、よかったら覗いていただけると嬉しいです。\n"
    "https://note.com/lifeworkfree\n"
    "よろしくお願いします☺️ \n"
    "\n"
    "https://www.kingdomran.jp/shindan/hyou.html"
)


PROFILE = {
    "nickname": "あおい",
    "avatar_url": None,
    "self_intro_text": SELF_INTRO_TEXT,
    "external_self_intro_text": SELF_INTRO_TEXT,
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1442802098847612968",
    "self_intro_posted_at": "2025-11-25T09:00:26.332000+00:00",
    "location_text": "関東（関西へ移住予定）",
    "nickname_public": False,
    "avatar_public": False,
    "self_intro_public": False,
    "location_public": False,
    "links_public": False,
}


# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "あおい": {
        "investment_style": ["インデックス投資", "個別株", "ゴールド"],
        "fire_status": ["サイドFIRE"],
        "skill": ["AI活用", "セルフリノベ", "kindle出版", "個人アプリ開発"],
        "interest": ["古民家リノベ", "note執筆"],
    },
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "あおい": [
        {"label": "note", "url": "https://note.com/lifeworkfree"},
    ],
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
    parser = argparse.ArgumentParser(description="Seed batch 27 of member_profiles/member_tags/member_links.")
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
