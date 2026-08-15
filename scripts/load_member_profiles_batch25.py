#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the twenty-fifth tag-display batch (1 member: はれとも).

The tag-display form response used the nickname "はれと" (Timestamp 8/16/2026 4:59:06),
but the member's own self-introduction and the master profile spreadsheet both use
"はれとも" - treated as the same person, canonical nickname "はれとも".
Same upsert pattern as load_member_profiles.py / batch2-24.
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
    "nickname": "はれとも",
    "avatar_url": "https://cdn.discordapp.com/avatars/1492307419370618962/6c5996770c985bcd6e5b68131ff2ba04.png?size=128",
    "self_intro_text": (
        "大変遅くなりました！！4月参加の”はれとも”です。\n"
        "\n"
        "2024年12月に20年以上勤めた外資を退職し、25年5月に日本社へ再就職。\n"
        "この先の時間とエネルギーを考えると、会社での時間が勿体なさ過ぎる・・と悩んでいたところに、F研の募集を見つけ応募しました。\n"
        "\n"
        "仕事の内容自体は嫌いではないのですが（法務で会社法周りの手続きを長年やっていました。今は総務で類似業務やってます）、組織でフルタイムで働く縛りが段々嫌になり、\n"
        "夫が自営で楽しそうに仕事をする姿を見て（都内にキッチンスタジオあり、食周り、YouTubeもやってます）、私もそろそろ、お金のために働くのをやめたいな～と。\n"
        "\n"
        "【ニックネーム】 はれとも\n"
        "\n"
        "【属性】 夫と二人暮らし\n"
        "\n"
        "【年齢・居住地】 50代半ば・東京\n"
        "\n"
        "【現在の仕事・収入源】 給与\n"
        "\n"
        "【投資・資産運用の状況】インデックス・PF調整中\n"
        "金融資産だけでは心配な額ですが、自宅不動産をカウントするとDie with Zeroならいけるのでは？！と考え始めたのがきっかけです。\n"
        "\n"
        "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】１～２年休んで旅したり、これからの人生をゆっくり考えたい。\n"
        "地方移住または二拠点生活も視野に入れています。\n"
        "\n"
        "【一言】\n"
        "F研究所の活動を見て、素敵なコミュニティだなと実感しています。色々参加したい！という気持ちはあるものの、時間とエネルギーがついていかず、もどかしい気持ちで眺めています。\n"
        "\n"
        "タイミングを見て突撃しますので、、よろしくお願いいたします。\n"
        "\n"
        "【趣味・好きな事】\n"
        "バレエ・ピラティス・ヨガ・散歩・旅行（マイル）・温泉\n"
        "カピバラのように生きたい😆\n"
        "\n"
        "【キングダム診断】 診断結果：王賁でした　キングダム知らないので当たってるか分かりません\n"
        "https://www.kingdomran.jp/shindan/ouhon.html"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1499327975261212753",
    "self_intro_posted_at": "2026-04-30T08:34:05.469000+00:00",
    "location_text": "東京",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "はれとも": {
        "investment_style": ["インデックス投資", "ポートフォリオ調整中"],
        "fire_status": ["FIRE検討中", "会社員（早期退職後再就職）"],
        "mbti": [],
        "skill": ["法務・会社法", "総務"],
        "interest": ["バレエ", "ピラティス", "ヨガ", "散歩", "旅行", "温泉"],
        "affiliation": [],
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
    parser = argparse.ArgumentParser(description="Seed batch 25 of member_profiles/member_tags/member_links.")
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
