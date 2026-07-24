#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the fifteenth tag-display batch (1 member: ひほひ).

Same upsert pattern as load_member_profiles.py / batch2-14.
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
    "nickname": "ひほひ",
    "avatar_url": "https://cdn.discordapp.com/avatars/1397922073011032187/37987eabad7b0d318dcff50e6f6bb143.png?size=128",
    "self_intro_text": (
        "【ニックネーム】\n"
        "　→ ひほひです。よろしくお願いします。NOTE：https://note.com/super_otter6605\n"
        "【属性】\n"
        "　→ 2024年12月に退職。世間様には専業主夫と説明しています。\n"
        "【年齢・居住地（ざっくりでOK）】\n"
        "　→ アラフィフ。四国在住。\n"
        "【現在の仕事・収入源】\n"
        "　→ 失業保険、妻の収入\n"
        "【投資・資産運用の状況】\n"
        "　→ 暗号資産がメイン。投資信託（S&P、オルカン、新興国インデックス）\n"
        "　　暗号資産が想定以上に上がりいつの間にかFIRE状態でした。\n"
        "\n"
        "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】\n"
        "　→ 有酸素運動ジャンキーでトレイルランニングやトライアスロンが趣味で、"
        "FIRE後は思う存分トレーニング三昧を予定していたのですが、ひざを痛め思うようなFIRE生活が送れていません。\n"
        "毎日、ひたすらダラダラしています。\n"
        "【一言】\n"
        "　→ 知っている先輩フォロワーさんが沢山いて嬉しいです。いろいろと情報交換させてください。"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1397948667213774990",
    "self_intro_posted_at": "2025-07-24T14:28:54.894000+00:00",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "ひほひ": [
        {"label": "note", "url": "https://note.com/super_otter6605"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "ひほひ": {
        "investment_style": ["暗号資産", "投資信託(S&P500/オルカン/新興国インデックス)"],
        "fire_status": ["FIRE済"],
        "mbti": [],
        "skill": [],
        "interest": ["トレイルランニング", "トライアスロン"],
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
    parser = argparse.ArgumentParser(description="Seed batch 15 of member_profiles/member_tags/member_links.")
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
