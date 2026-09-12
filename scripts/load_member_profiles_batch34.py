#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the thirty-fourth tag-display batch
(4 members: たき, Kimyhh, はぴりた, 岡).

Same upsert pattern as load_member_profiles.py / batch2-33.
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
        "nickname": "たき",
        "avatar_url": "https://cdn.discordapp.com/avatars/1039328950180139068/7db7ecf3ce554018377a069025bc8b91.png?size=128",
        "location_text": "茨城県",
        "self_intro_text": (
            "こんにちは。ほとんど諦めていましたが、今回こそは、と、気合を入れてプロフィール文を書いたのがよかったのか、当選できて嬉しいです♪\n"
            "\n"
            "【ニックネーム】\n"
            "「辻野たき」ですが、「たき」と呼んでください。\n"
            "「辻野たき」は、小説を冊子にしたときに作ったペンネームでもあります。\n"
            "\n"
            "【属性】\n"
            "　→ 大学の教員です。女性です。\n"
            "\n"
            "【年齢・居住地（ざっくりでOK）】\n"
            "　→ 50代前半。茨城県。夫・息子1名と暮らしています。\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "　→ 給与\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "　→ 2004年に始めました。主に中国株でした。\n"
            "　    2008年にリーマンショックで資産が4分の1になり、ショックでメンタルをやられました。\n"
            "　    その後は、投資信託を少し買っていたくらいでしたが、2019年から金額を増やしました。\n"
            "　    ほぼ、S&P500とnasdaqのインデックスファンドです。\n"
            "\n"
            "【無職になったらやりたいこと。無職の方は無職になって最初にやったこと】\n"
            "　→ 長期で海外旅行したい\n"
            "　　読書・小説を書いて文フリで販売する・庭仕事・ピアノ（こちらは、今もやっていますが）\n"
            "\n"
            "【一言】\n"
            "　→ 若い時から、お金があったら仕事は即座に辞めて、本を読んだり小説を書いたりしたい、と思ってきました。\n"
            "　　ただ、そのために仕事をしている状態が普通になってしまったせいか、\n"
            "　　今は、お金が貯まったとしても、本当に辞めて後悔しないのかと思い、 仕事を辞めるふんぎりがつきません。\n"
            "　　そこで、FIREしている皆さんと交流させていただき、リアルな状況に触れてみたいと思い、応募しました。\n"
            "　　どうぞよろしくお願い致します。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1492364137324482662",
        "self_intro_posted_at": "2026-04-11T03:22:17.123Z",
    },
    {
        "nickname": "Kimyhh",
        "avatar_url": None,
        "location_text": "京都府",
        "self_intro_text": (
            "みなさま、初めまして。\n"
            "Kimyhhと申します。\n"
            "\n"
            "【属性】\n"
            "既婚、子供１人。\n"
            "\n"
            "【年齢・居住地】\n"
            "38歳、14年前フランスから日本に移住し、京都に住んでいます。\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "外資系コンサルのマネジャーをしています。収入源は複数あります。\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "主にインデックスx不動産。\n"
            "\n"
            "【趣味、最近ハマっていること】\n"
            "ド田舎でゆっくりすること。\n"
            "\n"
            "【一言】\n"
            "ライフラインが給与以外の収入でカバー出来るようになってからの開放感が凄くて、好条件以外の仕事は一切やらないことにしました。会社に依存していた際と真っ逆の立場で無敵感を味わう毎日がこれからもしばらく続きます。\n"
            "\n"
            "とは言え、自分の目的を達成すれば、完全にFIREする予定であり、これからの居場所を探しながらここに辿り着きました。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1547949727524331531",
        "self_intro_posted_at": "2026-09-11T12:39:34.557Z",
    },
    {
        "nickname": "はぴりた",
        "avatar_url": None,
        "location_text": "東北地方",
        "self_intro_text": (
            "みなさま、はじめまして。よろしくお願いします。\n"
            "\n"
            "【ニックネーム】\n"
            "Happily_retired\n"
            "https://note.com/happily_retired\n"
            "\n"
            "【属性】\n"
            "おひとりさま\n"
            "\n"
            "【年齢・居住地】\n"
            "60代／東北の地方都市\n"
            "\n"
            "【現在の仕事・収入源】\n"
            "労働所得（個人事業主の事業収入、ちょこっとバイト給与）\n"
            "不労所得（不動産、配当）\n"
            "\n"
            "【投資・資産運用の状況】\n"
            "現物不動産が半分、有価証券（個別株、ファンドラップ含む投信）が半分、あとゴールド積立です。\n"
            "\n"
            "【一言】\n"
            "9年ほど前、52歳でサラリーマンを辞めてフリーランス開業と同時に半分リタイアしました。今でいうサイドFIREでしょうか。そろそろフルFIRE（もうこの歳なのでRetire Earlyじゃないですが（笑）しようかと考えています。最近の悩みは、やりたいことが見つからないこと……。情けないのですが。なので、このコミュニティで刺激がもらえたらと思って応募させていただきました。参加できてうれしいです。"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1408749307506458654",
        "self_intro_posted_at": "2025-08-23T09:46:48.206Z",
    },
    {
        "nickname": "岡",
        "avatar_url": "https://cdn.discordapp.com/avatars/1397811981620215810/62e1cba4d2e58046744a76af20fa0058.png?size=128",
        "location_text": "中部地方",
        "self_intro_text": (
            "みなさまはじめまして。\n"
            "参加させていただき、とてもうれしいです。\n"
            "\n"
            "【ニックネーム】岡\n"
            "【noteアカウント名】\n"
            "　岡 貴昭@静かなFIRE生活\n"
            "　https://note.com/takaaki_oka_\n"
            "【属性】セミリタイア済み。実態は主夫に近いです\n"
            "【年齢・居住地】30代後半・中部地方\n"
            "【現在の仕事・収入源】自営業だが配当収入メイン\n"
            "【投資・資産運用の状況】\n"
            "　日米の高配当株投資（個別株中心）＋最低限のインデックス投資（つみたて投資枠とiDeCo）\n"
            "【無職になって最初にやったこと】地方移住、コーチング（受ける側）\n"
            "【一言】\n"
            "　セミリタイア後、案の定ヒマを持て余しているため、この場がとてもありがたいです。\n"
            "　noteは、自身で決めた発信テーマの関係でちょっとしんみりしたものが多いのですが、\n"
            "　実生活ではゆるゆるとしています。\n"
            "　よろしくお願いします！"
        ),
        "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1397820524427481110",
        "self_intro_posted_at": "2025-07-24T05:59:43.273Z",
    },
]

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "たき": [
        {"label": "note（たきメモ）", "url": "https://note.com/alert_mink5401"},
        {"label": "note（たき／辻野たき）", "url": "https://note.com/clean_aster709"},
    ],
    "はぴりた": [
        {"label": "note", "url": "https://note.com/happily_retired"},
    ],
    "岡": [
        {"label": "note", "url": "https://note.com/takaaki_oka_"},
    ],
}

# category is one of: investment_style, fire_status, mbti, skill, consultation, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "たき": {
        "investment_style": ["インデックス投資信託"],
        "fire_status": ["会社員"],
        "mbti": ["INTP-T"],
        "interest": ["読書", "小説執筆", "庭仕事", "ピアノ", "海外旅行"],
    },
    "Kimyhh": {
        "investment_style": ["インデックス投資", "不動産"],
        "fire_status": ["会社員"],
        "interest": ["田舎暮らし"],
    },
    "はぴりた": {
        "investment_style": ["不動産", "個別株", "投資信託", "純金積立"],
        "fire_status": ["サイドFIRE"],
    },
    "岡": {
        "investment_style": ["高配当株", "インデックス投資信託", "iDeCo"],
        "fire_status": ["セミFIRE済み"],
        "mbti": ["INFJ-T"],
        "interest": ["地方移住", "コーチング"],
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
    parser = argparse.ArgumentParser(description="Seed batch 34 of member_profiles/member_tags/member_links.")
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
