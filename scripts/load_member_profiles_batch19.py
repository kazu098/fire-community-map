#!/usr/bin/env python3
"""Seed member_profiles/member_tags/member_links for the nineteenth tag-display batch (1 member: 閣下).

Same upsert pattern as load_member_profiles.py / batch2-18.
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
    "nickname": "閣下",
    "avatar_url": "https://cdn.discordapp.com/avatars/1513432885124796516/be4e7fc01d45ba7fd6ec79f4084cbe90.png?size=128",
    "self_intro_text": (
        "みなさま初めまして\n"
        "\n"
        "【ニックネーム】\n"
        "閣下\n"
        "\n"
        "【属性】\n"
        "妻と2人暮らし\n"
        "\n"
        "【年齢・居住地】\n"
        "50歳　神奈川\n"
        "\n"
        "【現在の仕事・収入源】\n"
        "都内で美容外科医として勤務\n"
        "\n"
        "30代は休みなんか返上で働きました。\n"
        "40代、まだFIREなんて言葉が無かった頃「ダウンシフト」なんて言って「走る速度を落としてワークライフバランスを見直して人間らしく生きるぜ」というムーブがあり、僕も週5勤務から週4勤務に減らしてみました。結果週5日分の仕事を4日でこなすようになり、むしろシフトダウンして高回転エンジンで走る事になってしまった。\n"
        "\n"
        "50を目前にしてこりゃいかんなと働く環境を変え、月の半分だけ働くようにしてみた。大好きな、天職だと思える仕事を売り上げやインセンティブを気にせずOPEのクオリティと患者満足度に注力して無理のないペースで働ける環境が出来上がりつつあるのかなぁ…ん？今の状況がほぼサイドFIREに近いのでは？と思っています。\n"
        "\n"
        "【投資・資産運用の状況】\n"
        "30代で病む寸前まで働いてある日リセットしたくなっちゃったんでしょうね。40歳までに稼いだ貯金全部親にあげちゃって😅\n"
        "\n"
        "いったんゼロから始めよっかという事で\n"
        "-大富豪アニキの教え\n"
        "-詳しいことはわかりませんが、お金の増やし方を教えてください\n"
        "-年間100万円の配当金が入ってくる最高の株式投資\n"
        "あたりの書籍を参考にぼちぼちやってます\n"
        "\n"
        "【これをやるためにFIREしたんだぜ】\n"
        "\n"
        "①地域貢献\n"
        "消防団で消防車運転してます\n"
        "あとはその関連で\n"
        "神社の祭りでテキ屋の親父やったり\n"
        "地域の盆踊りで音響やったり\n"
        "地域の子供向けハロウィンパーティで音響とDJやったり\n"
        "\n"
        "②音楽\n"
        "大学の軽音楽部のメンバーとやってますRedHotChiliPeppersのコピーバンドが20年以上続いていて、下手っぴながらギター弾いてます\n"
        "\n"
        "25年続く聖飢魔IIのコピーバンドに誘ってもらって3年前から歌ってます\n"
        "\n"
        "そこから派生して新たな聖飢魔IIのコピーバンドができ、やはり歌ってます\n"
        "\n"
        "年齢的に近い人たちが集まってやりたい曲を持ち寄ってやるセッション（始まりはmixiだった）ももう何年続いているかわからんけどありがたい事にやってます\n"
        "\n"
        "③ロードバイク\n"
        "神奈川に移住したのはロードバイクで海沿い→箱根の山の中を走るため！\n"
        "身体と向き合いながらいつまでやれるかを自問自答してる\n"
        "毎回楽しい\n"
        "なかなか痩せないけどなー😅\n"
        "\n"
        "④友人\n"
        "出張仕事時代にできた友人が全国に何人かいるから彼らに会いに行ってビールを飲む\n"
        "\n"
        "中高年になると友人がいなくなる、という話が新聞の連載にもなってて興味深いですが、自分は「この人は友人だなぁ」と思える人を大切にしていく、とにかくgiveの精神でいきたいですね\n"
        "\n"
        "⑤夢？\n"
        "デカい音でロックが聴けて、小さなライブもできる店。\n"
        "昔はたくさんあったのにー\n"
        "\n"
        "【一言】\n"
        "すんません。\n"
        "1発目から詰め込みすぎました。\n"
        "\n"
        "キングダム診断は輪虎だそうです。"
    ),
    "self_intro_url": "https://discord.com/channels/1389921372683112539/1389923387887063171/1513692436613038140",
    "self_intro_posted_at": "2026-06-08T23:53:19.934000+00:00",
}

MEMBER_LINKS: dict[str, list[dict[str, str]]] = {
    "閣下": [],
}

# category is one of: investment_style, fire_status, mbti, skill, interest, affiliation
MEMBER_TAGS: dict[str, dict[str, list[str]]] = {
    "閣下": {
        "investment_style": ["日本高配当株", "個別株"],
        "fire_status": ["サイドFIRE"],
        "mbti": [],
        "skill": ["美容外科", "音響", "DJ", "ギター", "ボーカル"],
        "interest": ["地域貢献", "音楽", "ロードバイク", "友人との交流", "ライブバー"],
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
    parser = argparse.ArgumentParser(description="Seed batch 19 of member_profiles/member_tags/member_links.")
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
