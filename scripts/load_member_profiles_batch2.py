#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the second tag-display batch (20 members).

Same upsert pattern as load_member_profiles.py, but reads self-intro data from
tmp/tag_display_self_intros.json (produced by fetch_self_intros.py against
config/self_intro_target_nicknames additions) and uses a separate hand-curated
tag/link dict for this batch so the two batches stay independently reviewable.
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
    "ほたて": [{"label": "note", "url": "https://note.com/shitagakisan"}],
    "さとりーまん": [
        {"label": "note", "url": "https://note.com/stry_mn"},
        {"label": "記事", "url": "https://note.com/stry_mn/n/n3f0af78fe0cb"},
    ],
    "soto": [],
    "きこ": [],
    "ちゃん": [
        {"label": "note", "url": "https://note.com/chanfire"},
        {"label": "記事", "url": "https://note.com/chanfire/n/nc160b89c1ac3"},
    ],
    "もふりびと。": [
        {"label": "note", "url": "https://note.com/mofmof_fire"},
        {"label": "記事", "url": "https://note.com/mofmof_fire/n/na6cc9596b52a"},
    ],
    "きらまりん": [
        {"label": "note", "url": "https://note.com/kiramarine"},
        {"label": "著書", "url": "https://amzn.to/3PXMNu8"},
    ],
    "あきら": [{"label": "note", "url": "https://note.com/rorotoreo"}],
    "Nyupy": [
        {"label": "note", "url": "https://note.com/nyupy"},
        {"label": "記事", "url": "https://note.com/nyupy/n/nb854f7641427"},
    ],
    "haru": [{"label": "note", "url": "https://note.com/eager_garlic148"}],
    "よな": [
        {"label": "note", "url": "https://note.com/yona47_fts"},
        {"label": "記事", "url": "https://note.com/yona47_fts/n/n3a07f19a3e3e"},
    ],
    "べる": [
        {"label": "note", "url": "https://note.com/bellbelljp"},
        {"label": "ゲーム", "url": "https://store.steampowered.com/app/3975150/_Journeys_of_Real_People/"},
    ],
    "とみお": [],
    "瑠璃": [{"label": "note", "url": "https://note.com/gifted_marten325"}],
    "りりぃ": [],
    "にょろ": [
        {"label": "note", "url": "https://note.com/chasopu"},
        {"label": "記事", "url": "https://note.com/chasopu/n/n35cb55c5883c"},
    ],
    "あーる": [{"label": "note", "url": "https://note.com/aru_410"}],
    "練炭": [{"label": "note", "url": "https://note.com/carbon_06"}],
    "こはん": [{"label": "note", "url": "https://note.com/kohan0"}],
    "あんぱんだ": [{"label": "note", "url": "https://note.com/anpanda_44075"}],
}

# category is one of: investment_style, fire_status, mbti, skill, interest
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "ほたて": {
        "investment_style": ["投資信託"],
        "fire_status": ["サイドFIRE目指し中"],
        "mbti": ["INTJ-A"],
        "skill": ["俳優業", "SNS運用"],
        "interest": ["読書", "犬"],
    },
    "さとりーまん": {
        "investment_style": ["米国株インデックス投資", "暗号資産", "金(ゴールド)", "米国債"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["ISTJ-T"],
        "skill": ["損害保険査定", "ストックフォト"],
        "interest": ["多拠点生活", "YouTube配信", "ブログ"],
    },
    "soto": {
        "investment_style": ["IFA運用", "オルカン"],
        "fire_status": ["サイドFIRE"],
        "mbti": ["ENFP-A"],
        "skill": ["マーケティング", "DX", "研修", "事業開発"],
        "interest": ["旅行", "アウトドア", "バイク"],
    },
    "きこ": {
        "investment_style": ["米国株", "日本株", "投資信託"],
        "fire_status": ["FIRE済"],
        "mbti": ["INTJ-A"],
        "skill": ["建築士"],
        "interest": ["温泉", "ドラム", "書道", "城巡り"],
    },
    "ちゃん": {
        "investment_style": ["インデックス投資(S&P500)", "暗号資産"],
        "fire_status": ["サイドFIRE目指し中"],
        "mbti": ["INFJ-A"],
        "skill": ["調理師", "占い師"],
        "interest": [],
    },
    "もふりびと。": {
        "investment_style": ["投資信託", "優待株", "高配当株"],
        "fire_status": ["バリスタFIRE準備中"],
        "mbti": [],
        "skill": [],
        "interest": ["楽器演奏"],
    },
    "きらまりん": {
        "investment_style": ["投資信託", "ETF", "債券", "暗号資産(BTC)"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["INTJ-A"],
        "skill": ["上場企業役員", "ビザスク相談"],
        "interest": ["note執筆", "コンテンツ共創"],
    },
    "あきら": {
        "investment_style": ["日本個別株"],
        "fire_status": ["FIRE済"],
        "mbti": ["INFJ-A"],
        "skill": [],
        "interest": ["旅行", "漫画", "犬"],
    },
    "Nyupy": {
        "investment_style": ["投資信託", "日本株"],
        "fire_status": ["FIRE済"],
        "mbti": ["ENTJ"],
        "skill": ["研究開発職", "マネジメント"],
        "interest": ["読書", "食べ歩き", "旅行", "観劇", "ボランティア"],
    },
    "haru": {
        "investment_style": ["米国株(S&P500)"],
        "fire_status": ["サイドFIRE"],
        "mbti": ["ENTJ"],
        "skill": ["パーソナルトレーナー"],
        "interest": ["筋トレ", "旅行", "園芸", "ゲーム", "料理"],
    },
    "よな": {
        "investment_style": ["インデックス投資(NISA/iDeCo)", "暗号資産"],
        "fire_status": ["会社員"],
        "mbti": ["INTP-A"],
        "skill": ["IT"],
        "interest": ["note執筆"],
    },
    "べる": {
        "investment_style": ["投資信託"],
        "fire_status": ["FIRE目指し中"],
        "mbti": [],
        "skill": ["ゲーム開発"],
        "interest": ["ゲーム", "旅行"],
    },
    "とみお": {
        "investment_style": ["米国個別株", "日本個別株", "投資信託", "ETF", "ロボアド", "不動産クラウドファンディング"],
        "fire_status": ["FIRE済"],
        "mbti": [],
        "skill": ["アウトドアガイド(SUP・シーカヤック・シュノーケリング)"],
        "interest": ["島暮らし"],
    },
    "瑠璃": {
        "investment_style": ["インデックス投資(オルカン)", "自宅不動産"],
        "fire_status": ["FI済のセミリタイア"],
        "mbti": [],
        "skill": ["経理職"],
        "interest": ["ピアノ", "旅行", "テニス"],
    },
    "りりぃ": {
        "investment_style": ["投資信託", "日本個別株"],
        "fire_status": ["サイドFIRE"],
        "mbti": ["ISTJ-A"],
        "skill": [],
        "interest": ["旅行", "47都道府県制覇"],
    },
    "にょろ": {
        "investment_style": ["高配当個別株", "NISA/iDeCo(S&P500)"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["ENFJ-A"],
        "skill": ["Instagram運用"],
        "interest": ["多拠点生活"],
    },
    "あーる": {
        "investment_style": ["インデックス投資(日本株/先進国株/新興国株/債券/REIT/ゴールド)"],
        "fire_status": ["FIRE済"],
        "mbti": ["INTP-A"],
        "skill": ["研究職(化学メーカー)"],
        "interest": ["旅行"],
    },
    "練炭": {
        "investment_style": ["インデックス投資(オルカン/S&P500/NASDAQ100)"],
        "fire_status": ["会社員"],
        "mbti": ["ISTJ-A"],
        "skill": ["エンジニアリング"],
        "interest": ["筋トレ", "ゲーム"],
    },
    "こはん": {
        "investment_style": ["不動産投資", "米国債", "REIT", "日米印インデックス", "個別株"],
        "fire_status": ["FIRE済"],
        "mbti": ["INFJ-T"],
        "skill": ["不動産投資"],
        "interest": ["旅行", "麻雀", "ランチ会"],
    },
    "あんぱんだ": {
        "investment_style": ["日本株(優待)", "インデックス投資", "米ドル建てETF", "企業型DC"],
        "fire_status": ["サイドFIRE目指し中"],
        "mbti": ["INTJ-A"],
        "skill": ["ITエンジニア", "Kindle出版"],
        "interest": ["博物館めぐり"],
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
    parser = argparse.ArgumentParser(description="Seed batch 2 of member_profiles/member_tags/member_links.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--self-intros", default="tmp/tag_display_self_intros.json")
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
