#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the twenty-fourth tag-display batch (1 member: もももす).

The tag-display form response only contained the opt-in nickname. Profile
content below is curated from the member's Discord self-introduction post.
Same upsert pattern as load_member_profiles.py / batch2-23.
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
    "競争率が高い中、参加できてとても嬉しいです🐣 \n"
    "\n"
    "【ニックネーム】\n"
    "　　もももす\n"
    "\n"
    "【属性】\n"
    "　　妻・子2人・猫2匹。個人事業主15年目。サイドFIREな感じ\n"
    "\n"
    "【年齢・居住地】\n"
    "　　42♂・福井で2拠点居住\n"
    "\n"
    "【現在の仕事・収入源】\n"
    "　　フリーランスITエンジニア（先月は2時間。今月は数十時間あるかも？）\n"
    "　　草刈り剪定（果樹栽培が趣味で去年スタートしてみたものの、年間数件）\n"
    "\n"
    "【投資・資産運用の状況】\n"
    "　　米国インデックスメイン（SP500/QQQ/FANG+）\n"
    "　　株の調子次第で収入０でも資産増加しそう\n"
    "\n"
    "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】\n"
    "　　個人事業主歴は長く、無職的な動きはたびたびしていましたが、最近は中古戸建のリフォームと畑作業\n"
    "\n"
    "【一言】\n"
    "　　似た価値観の人と楽しく交流できたらと思います。よろしくお願いします！\n"
    "\n"
    "【診断】\n"
    "　　適職にプログラマーがあり、ぴったりでした。\n"
    "　　https://www.kingdomran.jp/shindan/kaine.html"
)


PROFILE = {
    "nickname": "もももす",
    "avatar_url": "https://cdn.discordapp.com/avatars/446688943144960000/37de4a750511f9ce3df62d0cd459e594.png?size=128",
    "self_intro_text": SELF_INTRO_TEXT,
    "external_self_intro_text": SELF_INTRO_TEXT,
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1436307560776073226",
    "self_intro_posted_at": "2025-11-07T10:53:27.793000+00:00",
    "location_text": "福井で2拠点居住",
    "nickname_public": False,
    "avatar_public": False,
    "self_intro_public": False,
    "location_public": False,
    "links_public": False,
}


# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "もももす": {
        "investment_style": ["米国インデックス", "S&P500", "QQQ", "FANG+"],
        "fire_status": ["サイドFIRE", "個人事業主"],
        "skill": ["ITエンジニア", "プログラミング", "草刈り剪定"],
        "interest": ["果樹栽培", "中古戸建リフォーム", "畑作業", "猫"],
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
    parser = argparse.ArgumentParser(description="Seed batch 24 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    profiles = [PROFILE]
    tag_rows: list[dict[str, Any]] = []

    for nickname, categories in MEMBER_TAGS.items():
        for category, values in categories.items():
            for i, value in enumerate(values):
                tag_rows.append(
                    {"member_nickname": nickname, "category": category, "value": value, "sort_order": i}
                )

    print(f"Prepared {len(profiles)} profiles, {len(tag_rows)} tags, 0 links.")

    if args.dry_run:
        print(json.dumps(
            {"profiles": profiles, "tags": tag_rows, "links": []},
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
