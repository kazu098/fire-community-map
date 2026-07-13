#!/usr/bin/env python3
"""Seed member_profiles and member_tags from curated data + fetched self-intros.

Reads self-introduction text/links produced by fetch_self_intros.py and a
hand-curated tag list (agreed on with the community maintainer) and upserts
both into Supabase via the service role key. Safe to re-run: profiles are
upserted by nickname, and tags are upserted on (member_nickname, category,
value).
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


# Maps the canonical directory nickname to the lookup key used in
# tmp/self_intros.json (fetch_self_intros.py used the raw voice-channel
# screenshot names to disambiguate duplicate display names).
SELF_INTRO_LOOKUP_KEY = {
    "ひつじ": "ひつじ0",
    "みかん": "みかん0",
}

# External links (note / YouTube / blog) sourced from the member spreadsheet
# noteURL / product-article columns, plus URLs mentioned in self-intro text.
MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "Hiro-shi＠GL": [],
    "かず": [
        {"label": "note", "url": "https://note.com/kazu098"},
        {"label": "商品紹介", "url": "https://mia-cat.com/"},
    ],
    "きたさん": [{"label": "note", "url": "https://note.com/major_macaw6631"}],
    "たびお": [{"label": "note", "url": "https://note.com/tabikotabio"}],
    "ちぃ": [{"label": "note", "url": "https://note.com/cak"}],
    "とみと": [{"label": "note", "url": "https://note.com/vast_parrot6432"}],
    "はるた": [{"label": "note", "url": "https://note.com/haru_linkknot"}],
    "ひつじ": [{"label": "note", "url": "https://note.com/hitsuji_fire"}],
    "みかん": [
        {"label": "note", "url": "https://note.com/carista_lab"},
        {"label": "記事", "url": "https://note.com/carista_lab/n/nf2e49a2dff92"},
    ],
    "みなくさ": [
        {"label": "note", "url": "https://note.com/minakusa"},
        {"label": "記事", "url": "https://note.com/minakusa/n/nc6ebc6f8992f"},
    ],
    "カサドール（自給自足系投資家）": [
        {"label": "YouTube", "url": "https://www.youtube.com/channel/UCDAqN9UYZ0y89FRZbQBlqsw"},
    ],
    "カプチーノ": [{"label": "note", "url": "https://note.com/yochimi1009"}],
    "モンチ": [
        {"label": "note", "url": "https://note.com/monchi_blog_jp"},
        {"label": "ブログ", "url": "https://monchi-blog.jp"},
    ],
    "猫まる子": [{"label": "note", "url": "https://note.com/maruko_mofumofu"}],
}

# Hand-curated tags, agreed on in review before being reflected here.
# category is one of: investment_style, fire_status, mbti, skill, interest
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "Hiro-shi＠GL": {
        "investment_style": ["米国個別株", "米国インデックス投資"],
        "fire_status": ["マイクロ法人経営"],
        "mbti": ["INTJ-A"],
        "skill": ["技術顧問", "マイクロ法人設立"],
        "interest": ["旅行"],
    },
    "かず": {
        "investment_style": ["米国個別株"],
        "fire_status": ["会社員"],
        "mbti": ["INTJ-A"],
        "skill": ["エンジニアリング", "プロダクトマネジメント"],
        "interest": ["読書", "ランニング"],
    },
    "きたさん": {
        "investment_style": ["米国インデックス投資", "債券", "暗号資産", "金(ゴールド)"],
        "fire_status": ["窓際FIRE"],
        "mbti": ["INTJ-T"],
        "skill": ["宅建士", "行政書士", "FP2級", "簿記2級", "基本情報技術者"],
        "interest": ["グルメ"],
    },
    "たびお": {
        "investment_style": ["日本高配当株", "全世界インデックス投資(オルカン)", "債券"],
        "fire_status": ["FIRE済"],
        "mbti": ["ENFJ-A"],
        "skill": ["半導体エンジニアリング", "note執筆"],
        "interest": ["旅行", "バイクツーリング", "平日ランチ"],
    },
    "ちぃ": {
        "investment_style": ["米国ETF", "米国個別株", "投資信託", "暗号資産"],
        "fire_status": ["サイドFIRE"],
        "mbti": ["INTJ-T"],
        "skill": ["看護師"],
        "interest": ["家庭菜園"],
    },
    "とみと": {
        "investment_style": ["日本高配当株", "インデックス投資"],
        "fire_status": ["FIRE目指し中"],
        "mbti": ["INFJ-T"],
        "skill": ["産業カウンセラー", "キャリアコンサルタント", "発達障害学習支援"],
        "interest": [],
    },
    "はるた": {
        "investment_style": ["全世界インデックス投資(オルカン)", "個別株"],
        "fire_status": ["サイドFIRE"],
        "mbti": [],
        "skill": ["事務代行"],
        "interest": ["編み物"],
    },
    "ひつじ": {
        "investment_style": ["インデックス投資", "レバレッジETF(QQQ系)", "米国個別株"],
        "fire_status": ["会社員"],
        "mbti": ["INTJ-A"],
        "skill": ["IT", "AI解説"],
        "interest": ["移住検討"],
    },
    "みかん": {
        "investment_style": ["日本高配当株", "米国高配当ETF"],
        "fire_status": ["FIRE済"],
        "mbti": ["ENFP-A"],
        "skill": [],
        "interest": [],
    },
    "みなくさ": {
        "investment_style": ["優待株", "インデックス投資"],
        "fire_status": ["サイドFIRE"],
        "mbti": [],
        "skill": [],
        "interest": ["温泉・銭湯", "映画鑑賞", "ランチ会", "ジム"],
    },
    "カサドール（自給自足系投資家）": {
        "investment_style": ["インデックス投資", "日本高配当株"],
        "fire_status": ["FIRE済"],
        "mbti": [],
        "skill": ["漁業・アウトドアガイド", "YouTube発信"],
        "interest": ["釣り"],
    },
    "カプチーノ": {
        "investment_style": ["投資信託", "優待株", "日本高配当株"],
        "fire_status": ["コーストFIRE"],
        "mbti": ["ENFJ-A"],
        "skill": ["英語"],
        "interest": ["マラソン", "音楽(ブラスバンド)"],
    },
    "モンチ": {
        "investment_style": ["インデックス投資", "債券", "ソーシャルレンディング"],
        "fire_status": ["FIRE済"],
        "mbti": [],
        "skill": ["ブログ運営", "生成AI・プログラミング学習中"],
        "interest": [],
    },
    "猫まる子": {
        "investment_style": ["日本個別株", "全世界インデックス投資(オルカン)"],
        "fire_status": ["FIRE準備中"],
        "mbti": [],
        "skill": ["精神医学", "脳科学", "研究マネジメント"],
        "interest": ["note執筆"],
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
    parser = argparse.ArgumentParser(description="Seed member_profiles and member_tags.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--self-intros", default="tmp/self_intros.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")

    self_intros = json.loads(Path(args.self_intros).read_text(encoding="utf-8"))
    self_intro_by_key = {entry["nickname"]: entry for entry in self_intros}

    profiles: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []

    for nickname, categories in MEMBER_TAGS.items():
        lookup_key = SELF_INTRO_LOOKUP_KEY.get(nickname, nickname)
        intro = self_intro_by_key.get(lookup_key)
        if not intro or not intro.get("found"):
            raise SystemExit(f"No self-intro found for {nickname} (lookup key: {lookup_key})")

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
