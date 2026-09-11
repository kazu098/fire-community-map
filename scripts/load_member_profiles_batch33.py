#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-third tag-display batch
(4 members: チミヱ, natsu, Mayer, とり).

Same upsert pattern as load_member_profiles.py / batch2-32.
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
        "nickname": "チミヱ",
        "avatar_url": "https://cdn.discordapp.com/avatars/1395382666865541337/19cc83878066afd40addcb7dd58882b0.png?size=128",
        "location_text": "東京都",
        "self_intro_text": (
            "【ニックネーム】チミヱ\n"
            "【noteアカウント】\n"
            "https://note.com/chimie_2507\n"
            "魑魅魍魎部屋というフザけたアカウント名でこれから始めようと思っています。\n"
            "【属性】会社員\n"
            "【年齢・居住地】40代 東京都\n"
            "【投資】\n"
            "投資信託、IDeCo　投資を始めてまだ数ヶ月のド素人です。\n"
            "【現在の仕事・収源】給与収入のみ　\n"
            "【無職になったら】\n"
            "学び直しをしたいです。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1395561985940263023",
        "self_intro_posted_at": "2025-07-18T00:25:05.736Z",
    },
    {
        "nickname": "natsu",
        "avatar_url": "https://cdn.discordapp.com/avatars/1531904481959215239/1f8b82e8025bd0c82e72cb873bae7f1f.png?size=128",
        "location_text": "首都圏",
        "self_intro_text": (
            "みなさま、はじめまして　natsuと申します🏝️\n"
            "\n"
            "ずーっとnoteやyoutube等でフォローしていたFIRE研究所に参加することができてとてもとてもうれしいです☺️\n"
            "\n"
            "どうぞよろしくお願いいたします🙇‍♀️\n"
            "\n"
            "【ニックネーム】\n"
            "natsu\n"
            "\n"
            "【属性】\n"
            "🏝️フルタイムの仕事を卒業してサイドFIRE\n"
            "👥パートナーあり\n"
            "\n"
            "【年齢・居住地】\n"
            "40代／首都圏\n"
            "\n"
            "【これまでの仕事】\n"
            "IT,製造系の業界が長いです🔧\n"
            "若い頃は上海で働いてました🇨🇳\n"
            "その後も中華系企業とかかわりがあり中国語がいけます🍜\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "🇨🇳知り合いの会社のお手伝い\n"
            "🏝️個人で請け負っている地域創生に関する事業のお手伝い\n"
            "\n"
            "【投資・資産運用】\n"
            "10年以上前に何故か唐突にノープランで個別株を買い、暴落して狼狽売り💸した後は、\n"
            "ほぼインデックス投資のみです💵\n"
            "\n"
            "【好きなこと・最近やっていること】\n"
            "旅行🧳海🏖️散歩🚶‍♀️\n"
            "🇰🇷韓国映画・ドラマ（ノワールが好き）、　韓国語の勉強\n"
            "\n"
            "10年以上筋トレを続けてましたがトレーナーの知人に勧められて気分転換に始めたpilatesにハマってほぼ毎日通ってます🏋️‍♀️\n"
            "\n"
            "あとは、ベタですが昨日放送大学🏫に願書をだしましたｗ\n"
            "\n"
            "【一言】\n"
            "わたしはFIREといってもサイドFIREなので、できればもっともっと時間持ち⏰になれるようにしたいなーと思っております。\n"
            "もう少し好きなことで稼げる比率を高めて、このまま移住🏝️に向かって突き進むことを目標としています🤗\n"
            "\n"
            "noteは休職したころの気持ちの振り返りなど含んで暗いテンションなのですが、\n"
            "本当は結構絡みたがりなのでみなさまの投稿に色々レスなどさせていただくと思います😇\n"
            "\n"
            "どうぞよろしくお願いいたしますー！"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1547491089051684864",
        "self_intro_posted_at": "2026-09-10T06:17:06.624Z",
    },
    {
        "nickname": "Mayer",
        "avatar_url": "https://cdn.discordapp.com/avatars/1547545036063768653/cd046d9aacf722694a6e52f5a6693b46.png?size=128",
        "location_text": "東京都",
        "self_intro_text": (
            "初めまして。Mayerと申します。\n"
            "9月からFIRE研究所に参加させていただくことになりました。\n"
            "157名も応募があったそうなので、無理だろうなあ、と思っていたら当選メールを頂き、とても嬉しかったです。\n"
            "\n"
            "【ニックネーム】\n"
            "Mayer\n"
            "\n"
            "【属性】\n"
            "既婚\n"
            "\n"
            "【年齢・居住地（ざっくりでOK）】\n"
            "アラフィフ・東京都\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "失業保険を受給中です。\n"
            "2026年5月FIREしました。\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "インデックスと日本株がメインです。\n"
            "\n"
            "【趣味、最近ハマってること】\n"
            "趣味: 麻雀・プロ野球・漫画\n"
            "\n"
            "【無職になったらやりたいこと】\n"
            "無職になったからこそ、情報のアップデートしていきたいです。。。\n"
            "会社にいる時は否応なく新しいツールやアプリを使用し仕事していたのですが、今回discord を初めて使用し、超絶モタモタしてしまいました。。。５ヶ月無職生活をし、脳みそもヤバくなった気がします。\n"
            "\n"
            "【一言】\n"
            "10年以上、ニュージーランドに住んでいました。9年ほど前に帰国し、現在東京に住んでいます。\n"
            "海外生活に興味がある方がいらしたら何かお助けできれば幸いです。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1547562944408064000",
        "self_intro_posted_at": "2026-09-10T11:02:38.276Z",
    },
    {
        "nickname": "とり",
        "avatar_url": "https://cdn.discordapp.com/avatars/1431209697200836640/b4fd84c2ca49cc6aa6cc9366f38c1a65.png?size=128",
        "location_text": "東北・カナダ",
        "self_intro_text": (
            "■テンプレ\n"
            "【ニックネーム】\n"
            "　とり\n"
            "【属性】\n"
            "　→ サイドFIREです！\n"
            "【年齢・居住地（ざっくりでOK）】\n"
            "　→ アラフォー、東北\n"
            "【現在の仕事・収入源】\n"
            "　→ バーンアウトしたエンジニアにコーチングしてます笑\n"
            "【投資・資産運用の状況】\n"
            "　→ インデックスメインで自動化・放置です\n"
            "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】\n"
            "　→ とりあえずしばらく寝た後、ガツガツ働く癖が抜けずせかせかと勉強したりトレーニング受けたりしてました。今は人生をまったり楽しむことを学び中です。筋トレしたいです！\n"
            "【一言】\n"
            "　→ 参加できて本当に嬉しいです！よろしくお願いします〜！\n"
            "\n"
            "https://note.com/coast_fire\n"
            "\n"
            "https://www.kingdomran.jp/shindan/ousen.html"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1431572054590886000",
        "self_intro_posted_at": "2025-10-25T09:16:15.137Z",
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "チミヱ": [
        {"label": "note", "url": "https://note.com/chimie_2507"},
    ],
    "Mayer": [
        {"label": "note", "url": "https://note.com/lush_honest6202"},
    ],
    "とり": [
        {"label": "note", "url": "https://note.com/coast_fire"},
        {"label": "適職診断", "url": "https://www.kingdomran.jp/shindan/ousen.html"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "チミヱ": {
        "investment_style": ["投資信託", "iDeCo"],
        "fire_status": ["会社員"],
        "mbti": ["ENTJ"],
    },
    "natsu": {
        "investment_style": ["インデックス投資信託", "個別株", "企業型DC", "米国債"],
        "fire_status": ["サイドFIRE"],
        "skill": ["中国語"],
        "interest": ["旅行", "韓国映画・ドラマ", "韓国語学習", "ピラティス"],
    },
    "Mayer": {
        "investment_style": ["インデックス投資信託", "日本株"],
        "fire_status": ["FIRE済み"],
        "interest": ["麻雀", "プロ野球", "漫画"],
    },
    "とり": {
        "investment_style": ["インデックス投資", "個別株"],
        "fire_status": ["サイドFIRE"],
        "skill": ["コーチング"],
        "mbti": ["INFJ-T"],
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
    parser = argparse.ArgumentParser(description="Seed batch 33 of member_profiles/member_tags/member_links.")
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
