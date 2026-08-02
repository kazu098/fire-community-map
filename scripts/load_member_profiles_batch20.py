#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the twentieth tag-display batch (1 member: どーやん).

Same upsert pattern as load_member_profiles.py / batch2-19.
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
    "nickname": "どーやん",
    "avatar_url": "https://cdn.discordapp.com/avatars/1411758648295690242/e95540bf9e42b7641bb4f971673b9f02.png?size=128",
    "self_intro_text": (
        "みなさまはじめまして。\n"
        "どーやんと申します。\n"
        "まさか当選するとは思っておらず、会社でスマホ片手に一瞬固まりました。\n"
        "\n"
        "\n"
        "【ニックネーム】\n"
        "どーやん\n"
        "\n"
        "【属性】\n"
        "・妻、子ども2人（小学校低学年と未就学児）の4人家族\n"
        "・サイドFIREを現実的に模索中です\n"
        "\n"
        "【年齢・居住地】\n"
        "40代、首都圏\n"
        "\n"
        "【現在の仕事・収入源】\n"
        "現在は法務の仕事をしています。\n"
        "妻も共働きですが、家計はゆるっと分けています。たまに「これ、どっちの財布だっけ？」となります。\n"
        "\n"
        "【投資・資産運用の状況】\n"
        "・インデックス投資（オルカン）がメイン\n"
        "・初期の優待投資などの迷走期も含めると、投資歴は8年ほどです\n"
        "・サテライトは楽しさと興味重視で、金、ビットコイン、REIT、個別株などにも投資しています\n"
        "\n"
        "\n"
        "【無職になったらやりたいこと】\n"
        "・家族との時間を増やす\n"
        "・朝の思いつきで、昼には遠く離れた場所にいること\n"
        "・思いつくままに文章を書いたり、自分の考えを整理したりすること\n"
        "・いつかKindle本を出してみたいです\n"
        "\n"
        "【一言】\n"
        "FIRE研究所の活動内容に惹かれて応募しました。FIRE図鑑も読みましたが、本当にいろいろな方がいて、皆さんがそれぞれの形で動かれているのがとても素敵だなと思いました。これから少しずつ、皆さんと交流していけたらうれしいです。\n"
        "\n"
        "【SNS】\n"
        "noteをゆるめに書いています。時々、書いているうちに止まらなくなります。\n"
        "https://note.com/lucky_prawn6539\n"
        "\n"
        "【キングダム診断】\n"
        "キングダムは毎週読んでいますが、「カイネ」でした。\n"
        "周囲を見回して補佐に入るタイプというのは当たっているかもしれません。\n"
        "\n"
        "https://www.kingdomran.jp/shindan/kaine.html"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1502336590343569570",
    "self_intro_posted_at": "2026-05-08T15:49:15.202000+00:00",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "どーやん": [
        {"label": "note", "url": "https://note.com/lucky_prawn6539"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "どーやん": {
        "investment_style": ["インデックス投資", "金", "ビットコイン", "REIT", "個別株"],
        "fire_status": ["サイドFIRE"],
        "mbti": ["ENTJ"],
        "skill": ["法務"],
        "interest": ["読書・執筆", "旅行", "家族時間"],
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
    parser = argparse.ArgumentParser(description="Seed batch 20 of member_profiles/member_tags/member_links.")
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
