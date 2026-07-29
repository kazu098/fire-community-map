#!/usr/bin/env python3
"""Generate a note-style activity report draft from Discord export JSON.

This is intentionally deterministic: it does not call an LLM or publish to
note. The output is a Markdown draft that an editor can trim, rewrite, and
paste into note. Promotional sections are kept outside the generated body.
The default output is a reader-facing .md draft, not an internal review report.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DEFAULT_EVENT_RAW = "tmp/community_events_raw.json"
DEFAULT_EVENT_CURATED = "data/community_events_curated.json"
DEFAULT_POSTS_RAW = "tmp/community_posts_raw.json"
DEFAULT_OUTPUT_DIR = "tmp/note_drafts"

SECTION_RULES = (
    ("出版・制作プロジェクト", ("出版", "Kindle", "図鑑", "文学フリマ", "ホームページ", "HP", "ロゴ")),
    ("YouTube・収録", ("YouTube", "収録", "動画")),
    ("部活・趣味の活動", ("麻雀", "ゲーム", "読書会", "料理", "お料理", "ボドゲ", "スプラ")),
    ("寺子屋・オンラインイベント", ("寺子屋", "寺小屋", "オンライン", "勉強会", "講座")),
    ("オフ会・リアルイベント", ("オフ会", "飲み会", "ランチ", "大阪", "東京", "名古屋", "浅草", "リアル")),
)

POST_TYPE_LABELS = {
    "book": "読書・本の共有",
    "travel": "旅行・グルメ",
    "money_consultation": "お金の話・相談",
    "care_medical": "介護・医療",
    "parenting": "子育て",
    "real_estate": "不動産",
}

EVENT_ANNOUNCEMENT_RE = re.compile(
    r"(@everyone|開催します|開催しました|募集|締め切|〆切|リマインド|日程アンケート|イベントフォーラム|お知らせ)"
)
EVENT_REVIEW_RE = re.compile(r"(開催しました|開催されました|無事終了|始まりました|ありがとうございました|楽しかった|レポート|共有され)")

INFERRED_ACTIVITY_RULES = (
    ("静岡さわやかオフ会", ("静岡", "さわやか")),
    ("東京F研突発ゆる飲み会", ("東京F研突発ゆる飲み会",)),
    ("大阪・なんば みかんさんを囲む会", ("みかんさんを囲む会", "大阪")),
    ("オンライン読書会", ("オンライン読書会", "読書会")),
    ("オンラインお料理会 中毒カレー", ("お料理会", "中毒カレー")),
    ("ボドゲオフ会とスプラ部", ("ボドゲ", "スプラ")),
    ("スナックとみと", ("スナックとみと",)),
    ("新人交流会", ("新人交流会",)),
    ("少人数オンライン飲み会", ("少人数", "オンライン飲み会")),
    ("寺子屋後の飲み会", ("寺子屋後", "飲み会")),
    ("麻雀会", ("麻雀会",)),
)

EDITORIAL_TITLE_BY_SECTION = {
    "オフ会・リアルイベント": "オフ会が各地で開催されました！",
    "部活・趣味の活動": "部活とオンライン企画が盛り上がりました！",
    "寺子屋・オンラインイベント": "オンラインイベントが活発でした！",
    "出版・制作プロジェクト": "制作プロジェクトが進みました！",
    "YouTube・収録": "YouTube収録も行われました！",
}


@dataclass(frozen=True)
class Activity:
    title: str
    happened_at: datetime
    source: str
    summary: str
    participant_count: int | None
    permalink: str | None
    images: tuple[str, ...]
    channel_name: str | None = None


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(JST)


def parse_date(value: str, end_of_day: bool = False) -> datetime:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        suffix = "T23:59:59+09:00" if end_of_day else "T00:00:00+09:00"
        value = f"{value}{suffix}"
    parsed = parse_dt(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"Invalid date/datetime: {value}")
    return parsed


def month_range(value: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("--month must be YYYY-MM")
    year, month = (int(part) for part in value.split("-"))
    start = datetime(year, month, 1, tzinfo=JST)
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=JST)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=JST)
    return start, next_month - timedelta(seconds=1)


def clean_text(value: str | None, limit: int = 180) -> str:
    text = re.sub(r"<@!?\d+>|@everyone|@here", "", value or "")
    text = re.sub(r"https?://\S+", "", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "..."
    return text


def image_urls(item: dict[str, Any], max_count: int) -> tuple[str, ...]:
    urls: list[str] = []
    for attachment in item.get("attachments") or []:
        url = str(attachment.get("url") or "")
        if attachment.get("content_type") in IMAGE_CONTENT_TYPES and "cdn.discordapp.com/attachments/" in url:
            urls.append(url)
    return tuple(list(dict.fromkeys(urls))[:max_count])


def activity_title(item: dict[str, Any]) -> str:
    text = item_text_for_section(item)
    inferred_title = inferred_activity_title(text)
    if inferred_title:
        return inferred_title
    if EVENT_REVIEW_RE.search(text) and image_urls(item, 1):
        if "オフ会" in text or item.get("channel_name") == "オフ会":
            return "オフ会の様子"
        return "イベントの振り返り"
    for key in ("title", "name", "thread_name"):
        if item.get(key):
            return clean_text(str(item[key]), 60)
    content = clean_text(str(item.get("content") or ""), 60)
    return content or "名称未設定の活動"


def inferred_activity_title(text: str) -> str | None:
    for title, keywords in INFERRED_ACTIVITY_RULES:
        if all(keyword in text for keyword in keywords):
            return title
    return None


def item_text_for_section(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("name"),
        item.get("thread_name"),
        item.get("summary"),
        item.get("highlights"),
        item.get("description"),
        item.get("content"),
        item.get("channel_name"),
        item.get("discord_channel_name"),
    ]
    return "\n".join(str(part) for part in parts if part)


def section_for(item: dict[str, Any]) -> str:
    text = item_text_for_section(item)
    for section, keywords in SECTION_RULES:
        if any(keyword in text for keyword in keywords):
            return section
    return "その他の動き"


def event_datetime(item: dict[str, Any]) -> datetime | None:
    return parse_dt(
        item.get("starts_at")
        or item.get("scheduled_start_time")
        or item.get("posted_at")
    )


def event_summary(item: dict[str, Any]) -> str:
    inferred_title = activity_title(item)
    if inferred_title == "オンライン読書会":
        return "メンバー発案のオンライン読書会が開催されました。本を紹介する人だけでなく、聞き専やチャット参加もできる形式でした。"
    if inferred_title == "オンラインお料理会 中毒カレー":
        return "『FIREめし』で紹介された中毒カレーをテーマに、オンラインお料理会が開催されました。"
    if inferred_title == "ボドゲオフ会とスプラ部":
        return "ボドゲオフ会とスプラ部のお知らせがあり、遊びを通じた交流の場が広がりました。"
    if inferred_title == "東京F研突発ゆる飲み会":
        return "東京で突発のゆる飲み会が開催されました。直前の声かけにもかかわらず参加者が集まりました。"
    if inferred_title == "少人数オンライン飲み会":
        return "少人数で話せるオンライン飲み会が開催されました。大人数の会とは違う交流の形として試されました。"
    if inferred_title == "新人交流会":
        return "新しく入ったメンバーと既存メンバーが交流する新人交流会が行われました。"

    parts = []
    for key in ("summary", "highlights", "description", "content"):
        text = clean_text(str(item.get(key) or ""), 220)
        if text and text not in parts:
            parts.append(text)
    if parts:
        return past_tense_summary(parts[0])
    return "Discord上で開催された活動です。"


def past_tense_summary(text: str) -> str:
    replacements = (
        ("予定されている", "開催された"),
        ("予定されていた", "開催された"),
        ("告知・開催された", "開催された"),
        ("開催します", "開催されました"),
        ("募集かけ", "声をかけ"),
        ("募集する", "声をかける"),
        ("募集します", "声かけが行われました"),
        ("募集して", "声かけが行われて"),
        ("募集", "声かけ"),
        ("参加予定・参加者数", "参加者数"),
    )
    normalized = text
    for before, after in replacements:
        normalized = normalized.replace(before, after)
    return normalized


def collect_events(
    raw_events: list[dict[str, Any]],
    curated_events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    max_images_per_item: int,
) -> list[Activity]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in raw_events:
        message_id = str(item.get("discord_message_id") or "")
        if message_id:
            by_id[message_id] = item

    activities: list[Activity] = []
    seen: set[str] = set()
    for item in curated_events:
        dt = event_datetime(item)
        if dt is None or not (start <= dt <= end):
            continue
        message_id = str(item.get("discord_message_id") or "")
        if message_id and message_id in seen:
            continue
        seen.add(message_id)
        raw_item = by_id.get(message_id, item)
        activities.append(
            Activity(
                title=activity_title(item),
                happened_at=dt,
                source=section_for(item),
                summary=event_summary(item),
                participant_count=item.get("participant_count") or item.get("user_count"),
                permalink=item.get("discord_permalink"),
                images=image_urls(raw_item, max_images_per_item),
                channel_name=item.get("discord_channel_name") or item.get("channel_name"),
            )
        )

    for item in raw_events:
        dt = event_datetime(item)
        if dt is None or not (start <= dt <= end):
            continue
        message_id = str(item.get("discord_message_id") or "")
        if message_id and message_id in seen:
            continue
        text = item_text_for_section(item)
        is_structured_event = item.get("source_type") == "scheduled_event"
        inferred_title = inferred_activity_title(text)
        has_review_image = bool(EVENT_REVIEW_RE.search(text) and image_urls(item, 1))
        if not is_structured_event and not (inferred_title or has_review_image):
            continue
        if not is_structured_event and len(clean_text(str(item.get("content") or ""), 80)) < 20:
            continue
        seen.add(message_id)
        activities.append(
            Activity(
                title=activity_title(item),
                happened_at=dt,
                source=section_for(item),
                summary=event_summary(item),
                participant_count=item.get("participant_count") or item.get("user_count"),
                permalink=item.get("discord_permalink"),
                images=image_urls(item, max_images_per_item),
                channel_name=item.get("discord_channel_name") or item.get("channel_name"),
            )
        )
    return sorted(activities, key=lambda item: item.happened_at)


def collect_section_images(
    raw_events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    max_per_section: int,
) -> dict[str, list[tuple[str, str | None]]]:
    grouped: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    seen: set[str] = set()
    for item in raw_events:
        dt = parse_dt(item.get("posted_at"))
        if dt is None or not (start <= dt <= end):
            continue
        section = section_for(item)
        for url in image_urls(item, max_per_section):
            if url in seen:
                continue
            seen.add(url)
            if len(grouped[section]) < max_per_section:
                grouped[section].append((url, item.get("discord_permalink")))
    return dict(grouped)


def collect_post_topics(
    posts: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    limit_per_type: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in posts:
        dt = parse_dt(item.get("posted_at"))
        if dt is None or not (start <= dt <= end):
            continue
        content = clean_text(str(item.get("content") or ""), 170)
        if len(content) < 20:
            continue
        content_type = str(item.get("content_type") or "other")
        grouped[content_type].append({**item, "clean_content": content, "posted_at_jst": dt})

    for content_type, items in grouped.items():
        items.sort(key=lambda item: len(str(item.get("clean_content") or "")), reverse=True)
        grouped[content_type] = items[:limit_per_type]
    return dict(grouped)


def date_label(dt: datetime) -> str:
    return f"{dt.month}月{dt.day}日"


def period_label(start: datetime, end: datetime) -> str:
    if start.year == end.year and start.month == end.month:
        return f"{start.year}年{start.month}月"
    return f"{start.year}年{start.month}月{start.day}日〜{end.month}月{end.day}日"


def render_activity(activity: Activity, include_source_links: bool) -> list[str]:
    count = f"（参加者数: {activity.participant_count}名）" if activity.participant_count else ""
    lines = [
        f"### {activity.title}",
        "",
        f"{date_label(activity.happened_at)}に、{past_tense_summary(activity.summary)}{count}",
        "",
    ]
    if activity.images:
        lines.append("画像候補:")
        lines.extend(f"- {url}" for url in activity.images)
        lines.append("")
    if include_source_links and activity.permalink:
        lines.extend([f"編集メモ: {activity.permalink}", ""])
    return lines


def render_draft(
    activities: list[Activity],
    post_topics: dict[str, list[dict[str, Any]]],
    section_images: dict[str, list[tuple[str, str | None]]],
    start: datetime,
    end: datetime,
    include_source_links: bool,
    max_activities_per_section: int,
    template: str,
) -> str:
    label = period_label(start, end)
    sections: dict[str, list[Activity]] = defaultdict(list)
    for activity in activities:
        sections[activity.source].append(activity)

    top_sections = [name for name, _ in SECTION_RULES if sections.get(name)]
    top_sections.extend(name for name in ("その他の動き",) if sections.get(name))
    highlighted_section = max(top_sections, key=lambda name: len(sections[name]), default="")
    title_tail = EDITORIAL_TITLE_BY_SECTION.get(highlighted_section, "7月もF研らしい動きがありました！")

    show_internal_notes = include_source_links

    if template == "monthly":
        lines = [
            f"# 〖F研通信〗{title_tail}など、{label}の動き",
            "",
            "こんにちは！",
            "FIRE研究所です。",
            "",
            "毎月1回更新のF研通信です。F研通信では新メンバー応募への御礼と、直近のF研の動きについて書きます。",
            "",
            "それでは、新メンバー募集の御礼から！",
            "",
            "## 新メンバー募集の御礼",
            "",
            "[ここに今月の応募人数・選考状況・御礼文を入れてください。]",
            "",
            f"ここから{label}のF研の動きです！",
            "",
        ]
    else:
        lines = [
            f"# 〖F研通信〗{title_tail}",
            "",
            "こんにちは！",
            "FIRE研究所です。",
            "",
            f"今回は、{label}にF研で行われたことをまとめます。",
            "",
        ]
        if show_internal_notes:
            lines.extend(
                [
                    "<!-- 編集メモ: 募集御礼、さいごに、宣伝などの固定セクションは必要な場合だけ追加してください。 -->",
                    "",
                ]
            )

    if top_sections:
        overview = "、".join(name.replace("・", "、") for name in top_sections)
        lines.extend([f"この期間も、{overview}など、F研らしくいろいろなことが同時多発的に進みました。", ""])

    for section_name in top_sections:
        lines.extend([f"## {section_name}", ""])
        section_activities = sections[section_name]
        for activity in section_activities[:max_activities_per_section]:
            lines.extend(render_activity(activity, include_source_links))
        omitted = len(section_activities) - max_activities_per_section
        if omitted > 0 and show_internal_notes:
            lines.extend([f"[編集メモ: このセクションには他に{omitted}件の候補があります。必要なら期間を短くするか、出力上限を増やしてください。]", ""])
        if section_images.get(section_name):
            lines.extend(["画像候補:", ""])
            for url, permalink in section_images[section_name]:
                lines.append(f"- {url}")
                if include_source_links and permalink:
                    lines.append(f"  編集メモ: {permalink}")
            lines.append("")
        lines.append("* * *")
        lines.append("")

    if post_topics and template == "digest":
        lines.extend(["## Discordで盛り上がっていた話題", ""])
        for content_type, items in sorted(post_topics.items()):
            label = POST_TYPE_LABELS.get(content_type, content_type)
            lines.extend([f"### {label}", ""])
            for item in items:
                lines.append(f"- {item['clean_content']}")
                if include_source_links and item.get("discord_permalink"):
                    lines.append(f"  編集メモ: {item['discord_permalink']}")
            lines.append("")
        lines.append("* * *")
        lines.append("")

    if template == "monthly":
        lines.extend(
            [
                "## さいごに",
                "",
                "今月も色々ありました！",
                "",
                "[ここに、今月一番印象に残ったことや、来月に向けた一言を入れてください。]",
                "",
                "それでは今月もよろしくお願いします！",
                "",
                "<!-- 宣伝セクションは既存記事の固定文をコピーして、この下に貼ってください。 -->",
            ]
        )
    elif show_internal_notes:
        lines.extend(
            [
                "<!-- 宣伝セクションは既存記事の固定文をコピーして、この下に貼れます。不要ならこのコメントごと削除してください。 -->",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a note activity report draft from Discord JSON.")
    period = parser.add_mutually_exclusive_group()
    period.add_argument("--month", help="Target month in YYYY-MM, JST.")
    period.add_argument("--last-days", type=int, help="Generate a draft for the last N days from now.")
    parser.add_argument("--start", help="Explicit start date/datetime. Requires --end.")
    parser.add_argument("--end", help="Explicit end date/datetime. Requires --start.")
    parser.add_argument("--events-raw", default=DEFAULT_EVENT_RAW)
    parser.add_argument("--events-curated", default=DEFAULT_EVENT_CURATED)
    parser.add_argument("--posts-raw", default=DEFAULT_POSTS_RAW)
    parser.add_argument("--output", help="Output Markdown path. Defaults under tmp/note_drafts/.")
    parser.add_argument("--max-images-per-item", type=int, default=4)
    parser.add_argument("--max-section-images", type=int, default=8)
    parser.add_argument("--max-activities-per-section", type=int, default=8)
    parser.add_argument("--post-topic-limit", type=int, default=4)
    parser.add_argument(
        "--delivery",
        choices=("paste", "review"),
        default="paste",
        help="paste creates the note-ready .md deliverable; review includes internal source links.",
    )
    parser.add_argument(
        "--template",
        choices=("editorial", "digest", "monthly"),
        default="editorial",
        help="editorial is a loose F研通信-style article; digest is similar but minimal; monthly includes recruitment and closing placeholders.",
    )
    parser.add_argument("--include-source-links", action="store_true")
    args = parser.parse_args()
    if args.delivery == "review":
        args.include_source_links = True

    period_modes = sum(
        [
            bool(args.month),
            bool(args.last_days),
            bool(args.start or args.end),
        ]
    )
    if period_modes != 1:
        raise SystemExit("Choose exactly one period mode: --month, --last-days, or --start/--end.")

    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("--start and --end must be provided together.")
        start = parse_date(args.start)
        end = parse_date(args.end, end_of_day=True)
    elif args.month:
        start, end = month_range(args.month)
    else:
        end = datetime.now(JST)
        start = end - timedelta(days=args.last_days)

    raw_events = read_json(Path(args.events_raw), [])
    curated_events = read_json(Path(args.events_curated), [])
    posts_raw = read_json(Path(args.posts_raw), [])
    if not isinstance(raw_events, list):
        raise SystemExit(f"{args.events_raw} must contain a JSON array.")
    if not isinstance(curated_events, list):
        raise SystemExit(f"{args.events_curated} must contain a JSON array.")
    if not isinstance(posts_raw, list):
        raise SystemExit(f"{args.posts_raw} must contain a JSON array.")

    activities = collect_events(raw_events, curated_events, start, end, args.max_images_per_item)
    post_topics = collect_post_topics(posts_raw, start, end, args.post_topic_limit) if args.delivery == "review" else {}
    section_images = collect_section_images(raw_events, start, end, args.max_section_images)
    draft = render_draft(
        activities,
        post_topics,
        section_images,
        start,
        end,
        args.include_source_links,
        args.max_activities_per_section,
        args.template,
    )

    output = Path(args.output) if args.output else Path(DEFAULT_OUTPUT_DIR) / f"fken-tsushin-{start:%Y-%m-%d}_{end:%Y-%m-%d}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft, encoding="utf-8")
    print(f"Wrote {output} ({len(activities)} activities, {sum(len(v) for v in post_topics.values())} topic candidates).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
