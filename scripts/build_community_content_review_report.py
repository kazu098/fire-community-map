#!/usr/bin/env python3
"""Build a GitHub Issue-ready report for community content candidates."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


JST = timezone(timedelta(hours=9))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUTO_CANDIDATE_TYPES = {"book", "travel"}
REVIEW_CANDIDATE_TYPES = {
    "question_consultation",
    "money_consultation",
    "care_medical",
    "parenting",
    "real_estate",
}
TYPE_LABELS = {
    "book": "読んだ本",
    "travel": "旅行グルメ",
    "question_consultation": "質問・相談",
    "money_consultation": "お金の話・相談",
    "care_medical": "介護・医療",
    "parenting": "子育て",
    "real_estate": "不動産",
}
TRAVEL_PLACE_RE = re.compile(
    r"(北海道|青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|東京|神奈川|新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|京都|大阪|兵庫|奈良|和歌山|鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|大分|宮崎|鹿児島|沖縄|温泉|駅|空港|ホテル|旅館|カフェ|ランチ|レストラン|食堂|市場|神社|寺|城|公園|美術館|博物館|観光|旅行|帰省|出張|遠征|maps\.app\.goo\.gl|google\.com/maps|tabelog\.com|食べログ)",
    re.IGNORECASE,
)
CONSULTATION_HINT_RE = re.compile(
    r"(相談|質問|どう|どなたか|おすすめ|教えて|悩|迷|困|経験|知見|対策|注意|比較|メリット|デメリット|制度|保険|税|投資|介護|医療|子育て|不動産)",
    re.IGNORECASE,
)
BOOK_HINT_RE = re.compile(r"(読了|読みました|本|書籍|著者|Kindle|Audible|『.+?』|「.+?」)", re.IGNORECASE)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def parse_posted_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def truncate(text: str, limit: int = 260) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def image_attachment_count(item: dict[str, Any]) -> int:
    count = 0
    for attachment in item.get("attachments") or []:
        filename = str(attachment.get("filename") or "").lower()
        content_type = str(attachment.get("content_type") or "").lower()
        if content_type.startswith("image/") or any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
            count += 1
    return count


def known_message_ids(*collections: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for collection in collections:
        ids.update(str(item["discord_message_id"]) for item in collection if item.get("discord_message_id"))
    return ids


def title_guess(item: dict[str, Any]) -> str:
    text = str(item.get("content") or "").strip()
    content_type = str(item.get("content_type") or "")
    if content_type == "book":
        quoted = re.search(r"『([^』]{2,60})』|「([^」]{2,60})」", text)
        if quoted:
            return quoted.group(1) or quoted.group(2)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line:
        return truncate(first_line, 48)
    return f"{TYPE_LABELS.get(content_type, content_type)}候補"


def candidate_reason(item: dict[str, Any]) -> str | None:
    content_type = str(item.get("content_type") or "")
    text = str(item.get("content") or "")
    image_count = image_attachment_count(item)
    text_len = len(text.strip())

    if content_type == "book":
        if text_len >= 20 or BOOK_HINT_RE.search(text):
            return "読んだ本チャンネルの新規投稿。タイトル・要約を整えれば自動投稿候補にできます。"
        return None

    if content_type == "travel":
        if image_count and TRAVEL_PLACE_RE.search(text):
            return "画像付きで場所の手がかりがある旅行グルメ投稿。地図追加候補です。"
        if image_count:
            return "画像付き旅行投稿ですが、場所の確定確認が必要です。"
        if TRAVEL_PLACE_RE.search(text) and text_len >= 30:
            return "場所の手がかりがある旅行グルメ投稿。画像なしでも一覧候補として確認できます。"
        return None

    if content_type in REVIEW_CANDIDATE_TYPES:
        if text_len >= 80 and CONSULTATION_HINT_RE.search(text):
            return "暮らしの知恵として残す価値がありそうな相談・知見投稿。内容確認が必要です。"
        if text_len >= 140:
            return "まとまった投稿量があるため、暮らしの知恵候補として確認できます。"
        return None

    return None


def priority_bucket(item: dict[str, Any]) -> str:
    content_type = str(item.get("content_type") or "")
    if content_type in AUTO_CANDIDATE_TYPES:
        return "auto"
    return "review"


def build_report(
    raw: list[dict[str, Any]],
    curated: list[dict[str, Any]],
    travel_posts: list[dict[str, Any]],
    limit: int,
    lookback_days: int | None,
) -> tuple[int, str]:
    already_seen = known_message_ids(curated, travel_posts)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days) if lookback_days else None
    candidates: list[dict[str, Any]] = []

    for item in raw:
        message_id = str(item.get("discord_message_id") or "")
        if not message_id or message_id in already_seen:
            continue
        posted_at = parse_posted_at(item.get("posted_at"))
        if posted_at is None or (cutoff and posted_at < cutoff):
            continue
        reason = candidate_reason(item)
        if not reason:
            continue
        candidates.append({**item, "review_reason": reason, "posted_at_utc": posted_at})

    candidates.sort(key=lambda item: item["posted_at_utc"], reverse=True)
    candidates = candidates[:limit]

    auto = [item for item in candidates if priority_bucket(item) == "auto"]
    review = [item for item in candidates if priority_bucket(item) == "review"]
    today = datetime.now(JST).strftime("%Y-%m-%d")
    range_label = f"直近{lookback_days}日" if lookback_days else "取得差分全体"

    lines = [
        f"# 暮らしの知恵・旅行グルメ候補の確認が必要です - {today}",
        "",
        "Discordの投稿系チャンネルから、まだcuratedデータや旅行マップに入っていない候補を検出しました。",
        "承認するものは `tmp/community_posts_curated.json`、旅行マップに載せるものは `data/travel_posts.json` の更新対象として扱ってください。",
        "",
        f"対象範囲: {range_label}",
        f"候補件数: {len(candidates)}",
        f"自動投稿に寄せやすい候補: {len(auto)}",
        f"内容確認が必要な候補: {len(review)}",
        "",
    ]

    def append_section(title: str, items: list[dict[str, Any]]) -> None:
        lines.extend([f"## {title}", ""])
        if not items:
            lines.extend(["該当なし。", ""])
            return
        for i, item in enumerate(items, 1):
            content_type = str(item.get("content_type") or "")
            lines.extend(
                [
                    f"### {i}. {title_guess(item)}",
                    "",
                    f"- 種別: `{TYPE_LABELS.get(content_type, content_type)}`",
                    f"- チャンネル: `{item.get('channel_name')}`",
                    f"- 投稿者: `{item.get('member_nickname') or item.get('discord_author_display_name') or 'unknown'}`",
                    f"- 投稿日: `{item.get('posted_at')}`",
                    f"- 画像数: `{image_attachment_count(item)}`",
                    f"- 理由: {item['review_reason']}",
                    f"- Discord: {item.get('discord_permalink')}",
                    "",
                    "```text",
                    truncate(item.get("content") or "", 700),
                    "```",
                    "",
                ]
            )

    append_section("自動投稿に寄せやすい候補", auto)
    append_section("内容確認が必要な候補", review)
    return len(candidates), "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build community content review-needed report.")
    parser.add_argument("--raw", default="tmp/community_posts_raw.json")
    parser.add_argument("--curated", default="tmp/community_posts_curated.json")
    parser.add_argument("--travel-posts", default="data/travel_posts.json")
    parser.add_argument("--output", default="tmp/community_content_review_needed.md")
    parser.add_argument("--count-output", default="tmp/community_content_review_count.txt")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--lookback-days", type=int)
    args = parser.parse_args()

    raw = read_json(Path(args.raw), [])
    curated = read_json(Path(args.curated), [])
    travel_posts = read_json(Path(args.travel_posts), [])
    if not isinstance(raw, list):
        raise SystemExit(f"{args.raw} must contain a JSON array.")
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")
    if not isinstance(travel_posts, list):
        raise SystemExit(f"{args.travel_posts} must contain a JSON array.")

    count, report = build_report(raw, curated, travel_posts, args.limit, args.lookback_days)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")
    Path(args.count_output).write_text(str(count), encoding="utf-8")
    print(f"Review-needed community content candidates: {count}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
