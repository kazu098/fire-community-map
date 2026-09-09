#!/usr/bin/env python3
"""Seed member_profiles/member_tags for the thirty-second tag-display batch (1 member: takano).

Same upsert pattern as load_member_profiles.py / batch2-31.
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
    "nickname": "takano",
    "avatar_url": "https://cdn.discordapp.com/avatars/1546810611743068294/6c5996770c985bcd6e5b68131ff2ba04.png?size=128",
    "location_text": "岐阜",
    "self_intro_text": (
        "皆さま、はじめまして。takanoと申します。\n"
        "\n"
        "今月9月からFIRE研究所に参加させていただくことになりました。よろしくお願いします。\n"
        "\n"
        "【ニックネーム】\n"
        "\n"
        "Takano\n"
        "\n"
        "【属性】\n"
        "\n"
        "元自動車板金塗装工  \n"
        "独身  \n"
        "親族も無し\n"
        "たまたま運良く去年の10月からfire達成\n"
        "\n"
        "【年齢・居住地】\n"
        "\n"
        "約50歳  岐阜県在住\n"
        "\n"
        "【現在の仕事・収入源】\n"
        "\n"
        "仕事はしてないのでほぼ無収入\n"
        "田んぼを埋め立てたら駐車場として月数万円頂けるようになりました😆 \n"
        "\n"
        "【投資・資産運用の状況】\n"
        "\n"
        "投資暦は15年とかになりますが今だによく分からず、たまたま流行りに乗っかってみたらそこそこ儲かっちゃったかんじです😆 \n"
        "\n"
        "【無職になって最初にやったこと】\n"
        "\n"
        "秋からひと月程引きこもったら、冬はスノーボード、春から秋まではゴルフ、夏はウェイクボード、そんな一年を過ごしてました\n"
        "\n"
        "【一言】\n"
        "\n"
        "Fireしてこの一年それなりに楽しく充実した時間を過ごしてきたと思ってます。\n"
        "\n"
        "でもそれは働いてないだけで結局今までの人生の延長線上の上でしかないのではないかと\n"
        "\n"
        "改めて考えるとfireして数週間のんびりした生活をしてた時、如何に今までの自分が狭い世界や価値観の中で生きて来たのかと衝撃を受けたものです。\n"
        "\n"
        "そこから一年たった今の感想ですが、まだまだ私fireしただけで狭いとこで遊んでるのではないか！！そう思い始めました。\n"
        "\n"
        "それでまたまた運良く見つけたこのグループの色々な方と出会い知識を得ることが出来れば、自分の世界を広められるかも、そして人生をお互いより豊かに出来れば、と思い参加させていただきました。\n"
        "\n"
        "これからよろしくお願いします。"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1546865372999983225",
    "self_intro_posted_at": "2026-09-08T12:50:44.292Z",
}

# category is one of: investment_style, fire_status, mbti, skill, consultation, wants_to_know, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "takano": {
        "fire_status": ["FIRE済み"],
        "interest": ["スノーボード", "ゴルフ", "ウェイクボード"],
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
    parser = argparse.ArgumentParser(description="Seed batch 32 of member_profiles/member_tags.")
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

    print(f"Prepared {len(profiles)} profiles, {len(tag_rows)} tags.")

    if args.dry_run:
        print(json.dumps(
            {"profiles": profiles, "tags": tag_rows},
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
