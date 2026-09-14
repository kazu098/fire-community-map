#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-fifth tag-display batch
(1 member: さいふぉん).

Same upsert pattern as load_member_profiles.py / batch2-34.
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


PROFILES: list[dict[str, Any]] = [
    {
        "nickname": "さいふぉん",
        "avatar_url": "https://cdn.discordapp.com/avatars/1113816725184577628/f7febe1df39d93ac2a6544da1305726d.png?size=128",
        "location_text": "愛知県",
        "self_intro_text": (
            "みなさんはじめまして✨\n"
            "「さいふぉん」と申します！\n"
            "9月からFIRE研究所に参加させていただくことになりました。参加できて本当に嬉しいです。よろしくお願いします！\n"
            "\n"
            "【ニックネーム】\n"
            "さいふぉん\n"
            "\n"
            "【属性】\n"
            "2025年11月に材料メーカーを退職・FIRE\n"
            "妻・子ども2人の4人家族です\n"
            "\n"
            "【年齢・居住地】\n"
            "30代前半／愛知県\n"
            "\n"
            "【これまでの仕事】\n"
            "材料メーカーで約9年\n"
            "技術営業4年（欧州自動車メーカー担当）\n"
            "→ 🔬材料開発1年\n"
            "→ 🧠研究開発へのAI導入4年\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "マイクロ法人＋個人事業\n"
            "・革小物の制作・販売（ふるさと納税の返礼品にもなっています）\n"
            "・ハンドメイド販売支援\n"
            "・せどり\n"
            "\n"
            "【投資・資産運用】\n"
            "2014年から投資。\n"
            "個別株など色々経て、現在はほぼオルカンです。\n"
            "\n"
            "【好きなこと・最近やっていること】\n"
            "新しいことを試したり、気になったことを深掘りするのが好きです。\n"
            "\n"
            "最近は事業だけでなくプライベートでもAIで色々遊んでいて、\n"
            "📝 日記、ジャーナリング、人生設計\n"
            "🍺 ビールやワインなど、自分の好みの深掘り\n"
            "🎥 AIキャラクターを動かすYouTube動画づくり\n"
            "などをしています。\n"
            "\n"
            "映画はまだ全然詳しくないのですが、自分では経験できない人生や感情に触れて世界を広げられるのが魅力で、これから趣味にしたいと思っています🎬\n"
            "\n"
            "【FIREして感じたこと】\n"
            "人とのつながりや所属が大事なのは以前から分かっていたつもりでした。\n"
            "でも実際に会社を離れてみると、その存在が思っていた以上に大きかったことに気づきました。\n"
            "FIREしたからこそできる新しいつながりも作っていきたいと思い、FIRE研究所に応募させていただきました。\n"
            "\n"
            "【一言】\n"
            "自分とは違う経験をしている方のお話を聞いて、刺激を受けるのが好きです。\n"
            "\n"
            "自分の経験も共有しながら、お互いに新しい発見があったり、そこから何か面白いことが生まれたりしたら嬉しいです！\n"
            "\n"
            "イベントや活動にも色々参加してみたいです✨\n"
            "ぜひ気軽にお話ししてください。よろしくお願いします！"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1546894255430045777",
        "self_intro_posted_at": "2026-09-08T14:45:30.400Z",
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "さいふぉん": {
        "investment_style": ["インデックス投資信託"],
        "fire_status": ["FIRE済み"],
        "skill": ["技術営業", "AI活用"],
        "interest": ["ハンドメイド販売", "日記・ジャーナリング", "映画鑑賞"],
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
    parser = argparse.ArgumentParser(description="Seed batch 35 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    profiles = PROFILES
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
