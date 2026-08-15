#!/usr/bin/env python3
"""Backfill member_profiles for ネコ先生 (batch 8/9 form submission whose avatar/self-intro
were never captured -- only member_tags existed). Same upsert pattern as batch2-25.
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
    "nickname": "ネコ先生",
    "avatar_url": "https://cdn.discordapp.com/avatars/1535502507697119272/49afbbe9b69377bd213ce0bb73b21c49.png?size=128",
    "self_intro_text": (
        "みなさま、初めまして。\n"
        "ネコ先生と申します。\n"
        "2026年8月から参加させて頂きます。ようやく参加出来たので、とても嬉しいです。\n"
        "\n"
        "【属性】\n"
        "コーストFIRE/キャリアの模索中、既婚、子供1人\n"
        "\n"
        "【年齢・居住地】\n"
        "40歳前半／中国地方\n"
        "\n"
        "【現在の仕事・収入源】\n"
        "医療職として20年弱を過ごしてきました。主に内科領域に携わり、クリニックから病院まで勤務経験があります。現在は勤務を継続していますが、将来的にには週数回の勤務に移行することを検討しています。\n"
        "\n"
        "【投資・資産運用の状況】\n"
        "投資の開始時期は20年前ですが、大負けしてから距離をおいていました。投資を再開してから13年位です。\n"
        "\n"
        "生活防衛費を除くと、オルカンとSP500で3/4、日本個別株が1/4です。富士フイルムに期待しているのですが、先日の決算後に暴落しています。\n"
        "\n"
        "【趣味、最近ハマっていること】\n"
        "最近はnoteの記事を書くことにハマっています。noteを始めた契機はFIRE研究所の応募の際の自己開示が目的だったのですが、読者の方の反応が楽しみになっています。\n"
        "https://note.com/life_of_dr_neko\n"
        "\n"
        "【一言】\n"
        "元気に過ごせる時間は限られています。元気な時にしか出来ないこともあります。一方で、老いたり、病んだりすることで得られる発見もあります。人生を楽しむにも受け入れるにも、余裕が必要だと思います。自分自身のキャリアや人生をどのように設計するか模索中ですが、FIRE研究所のメンバーのみなさまを参考にさせて頂ければ幸いです。これから宜しくお願い致します。"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1535518297569763410",
    "self_intro_posted_at": "2026-08-08T05:21:30.691000+00:00",
    "location_text": "中国地方",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "ネコ先生": [
        {"label": "note", "url": "https://note.com/life_of_dr_neko"},
    ],
}

MEMBER_TAGS: dict[str, dict[str, list[str]]] = {}


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
    parser = argparse.ArgumentParser(description="Seed batch 26 of member_profiles/member_tags/member_links.")
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

    if tag_rows:
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
