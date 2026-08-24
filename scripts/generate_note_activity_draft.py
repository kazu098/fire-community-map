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
import calendar
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
    "book": "本の話",
    "travel": "旅行",
    "question_consultation": "質問・相談",
    "note": "note",
    "money_consultation": "お金の話・相談",
    "care_medical": "介護・医療",
    "parenting": "子育て",
    "real_estate": "不動産",
}

PUBLIC_IMAGE_TOPIC_TYPES = {"book", "travel", "note"}
PUBLIC_SENSITIVE_TOPIC_RE = re.compile(r"(ロゴ|名刺|規約|転載厳禁|スクリーンショット|Screenshot|個人情報|口座|証券)")

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

HALF_LABELS = {
    "first": "前半",
    "second": "後半",
}

HALF_OUTPUT_SUFFIX = {
    "first": "first-half",
    "second": "second-half",
}

BANNED_READER_PHRASES = (
    "今回は、",
    "まとめます",
    "振り返ります",
    "投稿されていました",
    "共有されていました",
    "投稿もありました",
    "投稿では、",
    "Discord上で開催された活動です。",
)

TRAVEL_KEYWORDS = (
    "北海道",
    "青森",
    "奄美",
    "加計呂麻島",
    "イビザ",
    "スペイン",
    "天売島",
    "焼尻島",
    "神居古潭",
    "丸瀬布",
    "タウシュベツ",
    "三内丸山遺跡",
    "八甲田丸",
    "ワラッセ",
    "ダナン",
    "ホイアン",
)

MONEY_KEYWORDS = (
    "円安",
    "外貨",
    "外貨建",
    "MMF",
    "債券",
    "個人向け国債",
    "リバランス",
    "暴落",
    "FIRE",
    "働き方",
    "社会貢献",
    "ボランティア",
)

CARE_KEYWORDS = (
    "介護",
    "認知症",
    "在宅介護",
    "介護ベッド",
    "医療",
    "体調",
    "家族",
)


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


def month_half_range(value: str, half: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("--month must be YYYY-MM")
    year, month = (int(part) for part in value.split("-"))
    if half == "first":
        return (
            datetime(year, month, 1, tzinfo=JST),
            datetime(year, month, 15, 12, 0, 0, tzinfo=JST),
        )
    last_day = calendar.monthrange(year, month)[1]
    return (
        datetime(year, month, 15, 12, 0, 1, tzinfo=JST),
        datetime(year, month, last_day, 12, 0, 0, tzinfo=JST),
    )


def clean_text(value: str | None, limit: int | None = 180) -> str:
    text = re.sub(r"<@!?\d+>|@everyone|@here", "", value or "")
    text = re.sub(r"https?://\S+", "", text)
    text = " ".join(text.split())
    if limit and len(text) > limit:
        return text[: limit - 1] + "..."
    return text


def example_text(value: str, limit: int = 100) -> str:
    text = clean_text(value, limit)
    text = re.sub(r"[\wぁ-んァ-ヶ一-龠々ー]+さん[、,\s]", "", text)
    text = re.sub(r"^[\wぁ-んァ-ヶ一-龠々ー]+です[。,.、\s]*", "", text)
    return text.strip()


def unique_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def keyword_hits(texts: list[str], keywords: tuple[str, ...], limit: int = 6) -> list[str]:
    joined = "\n".join(texts)
    return [keyword for keyword in keywords if keyword in joined][:limit]


def has_any(texts: list[str], keywords: tuple[str, ...]) -> bool:
    joined = "\n".join(texts)
    return any(keyword in joined for keyword in keywords)


def topic_has_sensitive_public_content(texts: list[str]) -> bool:
    return any(PUBLIC_SENSITIVE_TOPIC_RE.search(text) for text in texts)


def is_public_sensitive_text(text: str) -> bool:
    return bool(PUBLIC_SENSITIVE_TOPIC_RE.search(text))


def book_titles(texts: list[str], limit: int = 6) -> list[str]:
    titles: list[str] = []
    for text in texts:
        titles.extend(re.findall(r"『([^』]+)』", text))
    return unique_preserve_order(titles)[:limit]


def topic_focus_paragraphs(content_type: str, texts: list[str]) -> list[str]:
    paragraphs: list[str] = []
    if content_type == "book":
        if has_any(texts, ("FIRE", "自由権", "民主主義", "資本主義", "宇沢弘文")):
            paragraphs.append("印象的だったのは、本の感想がそのままFIREや自由、社会の仕組みの話につながっていたことです。投資や節約のテクニックだけではなく、「自分がどう生きるか」を考える材料として本が読まれていました。")
        if has_any(texts, ("悲嘆", "最愛", "脳科学", "神様のカルテ", "医療")):
            paragraphs.append("一方で、喪失や医療のような重いテーマの本も話題になりました。読み終えた感想が単なるおすすめで終わらず、家族や自分のこれからを考える入口になっていたのが印象的です。")
        if has_any(texts, ("れんげ荘", "リーンFIRE", "月10万円", "会社を辞め")):
            paragraphs.append("『れんげ荘』のように、会社を辞めた後の小さな暮らしを想像させる本も読まれていました。FIRE後の生活を、数字ではなく日々の手触りとして考える話題になっていたと思います。")
    elif content_type == "travel":
        if has_any(texts, ("ネパール", "カトマンズ", "ナガルコット", "ヒマラヤ", "エベレスト", "チャング・ナラヤン", "マウンテンフライト")):
            paragraphs.append("特に面白かったのは、ネパール旅行の企画です。カトマンズとナガルコットを中心に、ヒマラヤの夕日、星空、日の出、チャング・ナラヤンまでのハイキング、カトマンズの世界遺産巡り、早朝のマウンテンフライトでエベレストを空から見る、という流れが出ていました。")
            paragraphs.append("ただ「行きたいね」で終わらず、日程、直行便、航空券やホテル、現地ガイド、送迎、マウンテンフライトまで含めた概算予算まで話が進んでいたのが良いところです。国内の週末旅だけでなく、海外で数日間合流するような企画まで自然に立ち上がるのは、F研の旅行チャンネルらしい面白さだと思います。")
        if has_any(texts, ("北海道", "小樽", "天狗山", "札幌", "旭川")):
            paragraphs.append("旅行では、北海道の夏の空気や小樽の天狗山など、行った人だからこそ出てくる具体的なおすすめが目立ちました。地名の羅列ではなく、天気や季節感まで含めて旅先の様子が伝わっていました。")
        if has_any(texts, ("スリランカ", "サーフィン", "ミリッサ")):
            paragraphs.append("スリランカでサーフィンを始めた話もありました。年齢を重ねてから新しいことを始める話は、旅行というより「これからの時間をどう使うか」というF研らしいテーマにもつながっています。")
        if has_any(texts, ("インド", "RRR", "K.G.F", "テルグ語", "カンナダ語")):
            paragraphs.append("インド映画から、言語、宗教、旅のハードルまで話が広がっていたところも印象的でした。『RRR』や『K.G.F』の言語の違い、バガヴァット・ギーターの言葉など、映画を入口に知らない国を知っていく面白さがありました。")
        if has_any(texts, ("姫路", "神戸", "小豆島", "石川県")):
            paragraphs.append("姫路のホテル事情、小豆島、石川の建物など、近場の旅の話も出ていました。大きな旅行記だけでなく、日帰りや家族旅行の小さな気づきが集まるのも、このチャンネルの良さです。")
    elif content_type == "question_consultation":
        if has_any(texts, ("Discord", "ボイチャ", "マイク", "顔出し", "注意事項")):
            paragraphs.append("Discordの使い方やボイスチャット参加時の説明も話題になりました。新しく入った人が安心して参加できるように、細かい不安を先回りして減らそうとしている動きが見えます。")
    elif content_type == "money_consultation":
        if has_any(texts, ("こどもNISA", "児童手当", "教育資金", "学資保険", "生前贈与")):
            paragraphs.append("お金の話では、こどもNISAをきっかけに、教育資金、児童手当、学資保険、生前贈与まで話が広がりました。制度を使うかどうかだけでなく、子どもにどうお金を渡すのか、金融教育としてどう扱うのかまで踏み込んだ相談になっていました。")
        if has_any(texts, ("新NISA", "非課税", "キャッシュ", "投資への抵抗")):
            paragraphs.append("新NISAの枠をどう使うかという話も、家計全体の優先順位や日本での投資への抵抗感の話につながっていました。数字の最適解だけでは割り切れないところまで話せるのが、このチャンネルの濃さだと思います。")
    elif content_type == "care_medical":
        if has_any(texts, ("介護", "認知症", "在宅", "家族")):
            paragraphs.append("介護の話では、制度や手続きだけでなく、家族としてどう向き合うかという現実的な悩みが出ていました。資産形成とは別の意味で、暮らしを支える知恵が集まっていました。")
        if has_any(texts, ("医療", "体調", "病院", "検査")):
            paragraphs.append("医療や体調の話も、経験者の言葉があることで少し相談しやすくなっていました。ひとりで抱えやすいテーマほど、こうした場がある意味は大きいと感じます。")
    elif content_type == "note":
        if has_any(texts, ("note", "記事", "書く", "発信")):
            paragraphs.append("noteの話題では、書いたものをどう届けるか、どう続けるかという発信の工夫が話されていました。完成品だけでなく、書く途中の迷いも共有できる場になっています。")
    elif content_type == "parenting":
        paragraphs.append("子育ての話では、家庭ごとの事情を前提にしながら、無理なく続けられる選択肢を探す会話がありました。")
    elif content_type == "real_estate":
        paragraphs.append("不動産の話では、物件や制度の知識だけでなく、生活設計としてどう判断するかという視点で会話が進んでいました。")
    return paragraphs[:3]


def topic_heading(content_type: str, texts: list[str], label: str) -> str:
    if content_type == "book" and has_any(texts, ("FIRE", "自由", "れんげ荘", "民主主義", "宇沢弘文")):
        return "本の話は、FIRE後の暮らし方まで広がりました"
    if content_type == "travel" and has_any(texts, ("ネパール", "カトマンズ", "ナガルコット", "ヒマラヤ", "エベレスト")):
        return "旅の話には、ネパール旅行企画と新しい挑戦がありました"
    if content_type == "travel":
        return "旅の話には、季節感と新しい挑戦がありました"
    if content_type == "money_consultation" and has_any(texts, ("こどもNISA", "児童手当", "教育資金", "生前贈与")):
        return "こどもNISAの話は、家族のお金の渡し方まで深まりました"
    if content_type == "question_consultation" and has_any(texts, ("Discord", "ボイチャ", "マイク", "顔出し", "注意事項")):
        return "参加しやすい場づくりの話もありました"
    return label


def final_reader_cleanup(text: str) -> str:
    cleaned = text
    for phrase in BANNED_READER_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    cleaned = cleaned.replace("共有された", "広がった")
    cleaned = cleaned.replace("投稿が続きました", "話が続きました")
    cleaned = cleaned.replace("共有があり", "話もあり")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.rstrip() + "\n"


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
        is_announcement_only = bool(EVENT_ANNOUNCEMENT_RE.search(text) and not has_review_image)
        if not is_structured_event and not (inferred_title or has_review_image):
            continue
        if not is_structured_event and is_announcement_only:
            continue
        if not is_structured_event and not image_urls(item, 1) and re.search(r"(ありがとう|ありがとうございます|レポート)", text):
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
    deduped: list[Activity] = []
    seen_keys: set[tuple[str, str]] = set()
    for activity in sorted(activities, key=lambda item: item.happened_at):
        key = (activity.title, activity.happened_at.strftime("%Y-%m-%d"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if "【メモ】" in activity.title:
            continue
        deduped.append(activity)
    return deduped


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
        content = clean_text(str(item.get("content") or ""), 600)
        if len(content) < 20:
            continue
        content_type = str(item.get("content_type") or "other")
        grouped[content_type].append({**item, "clean_content": content, "posted_at_jst": dt})

    for content_type, items in grouped.items():
        items.sort(key=lambda item: len(str(item.get("clean_content") or "")), reverse=True)
        grouped[content_type] = items[:limit_per_type]
    return dict(grouped)


def collect_topic_images(
    posts: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    max_per_type: int,
) -> dict[str, list[str]]:
    grouped: dict[str, list[tuple[int, datetime, str]]] = defaultdict(list)
    seen: set[str] = set()
    for item in posts:
        dt = parse_dt(item.get("posted_at"))
        if dt is None or not (start <= dt <= end):
            continue
        content_type = str(item.get("content_type") or "other")
        if content_type not in PUBLIC_IMAGE_TOPIC_TYPES:
            continue
        text = str(item.get("content") or "")
        if PUBLIC_SENSITIVE_TOPIC_RE.search(text):
            continue
        score = 0
        if has_any([text], ("ネパール", "カトマンズ", "ナガルコット", "ヒマラヤ", "エベレスト")):
            score += 50
        if has_any([text], ("FIRE", "自由", "れんげ荘", "民主主義", "宇沢弘文", "神様のカルテ")):
            score += 20
        if has_any([text], ("スリランカ", "サーフィン", "北海道", "小樽", "平戸", "石川", "小豆島")):
            score += 10
        for url in image_urls(item, max_per_type):
            if url in seen:
                continue
            seen.add(url)
            grouped[content_type].append((score, dt, url))
    return {
        content_type: [
            url
            for _, _, url in sorted(items, key=lambda item: (item[0], item[1]), reverse=True)[:max_per_type]
        ]
        for content_type, items in grouped.items()
    }


def date_label(dt: datetime) -> str:
    return f"{dt.month}月{dt.day}日"


def period_label(start: datetime, end: datetime) -> str:
    if start.year == end.year and start.month == end.month and start.day == 1 and end.day == 15:
        return f"{start.year}年{start.month}月前半"
    if start.year == end.year and start.month == end.month and start.day == 15 and start.hour == 12:
        return f"{start.year}年{start.month}月後半"
    if start.year == end.year and start.month == end.month and start.day == 1 and end.day >= 28:
        return f"{start.year}年{start.month}月"
    if start.year == end.year and start.month == end.month:
        return f"{start.year}年{start.month}月{start.day}日〜{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日〜{end.month}月{end.day}日"


def render_activity(activity: Activity, include_source_links: bool) -> list[str]:
    if activity.summary == "Discord上で開催された活動です。":
        return []
    if len(clean_text(activity.summary, 80)) < 8 and not activity.images:
        return []
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


def render_topic_section(
    content_type: str,
    items: list[dict[str, Any]],
    topic_images: dict[str, list[str]],
) -> list[str]:
    label = POST_TYPE_LABELS.get(content_type, content_type)
    texts = [str(item.get("clean_content") or "") for item in items]
    if not texts:
        return []
    focus_paragraphs = topic_focus_paragraphs(content_type, texts)
    if content_type in {"question_consultation", "note", "care_medical", "parenting", "real_estate"} and not focus_paragraphs:
        return []

    lines = [f"## {topic_heading(content_type, texts, label)}", ""]
    if content_type == "book":
        titles = book_titles(texts)
        if titles:
            lines.append(f"{label}では、" + "、".join(f"『{title}』" for title in titles) + "など、幅広い本の話がありました。")
        else:
            lines.append("本の話では、読んだ本の感想から次に試してみたいことまで、知的好奇心が広がる会話がありました。")
        if any("裁判" in text or "傍聴" in text for text in texts):
            lines.append("本の話から裁判傍聴の話題にも広がり、実際に行く時の注意点や楽しみ方まで具体的な会話になっていました。")
        lines.append("読んで終わりではなく、そこから自分の暮らしや次の行動に結びついていくのがF研らしいところです。")
    elif content_type == "travel":
        hits = keyword_hits(texts, TRAVEL_KEYWORDS)
        if hits:
            lines.append("旅行チャンネルでは、" + "、".join(hits) + "など、旅先の話題が続きました。")
        else:
            lines.append("旅行チャンネルでは、国内外の旅先や現地で見つけたものの話で盛り上がりました。")
        lines.append("実際に行った人の感想やおすすめが出てくるので、次に行きたい場所の候補が自然に増えていくような時間でした。")
        lines.append("観光地の名前だけでなく、食べもの、移動、季節感まで話が広がるので、旅の空気が伝わってくるチャンネルになっています。")
    elif content_type == "question_consultation":
        lines.append("質問・相談では、メンバー同士の経験や視点が行き交う実用的な会話がありました。")
        lines.append("気軽な問いかけから具体的な選択肢が集まっていくところに、コミュニティで相談できる価値が出ていました。")
    elif content_type == "note":
        lines.append("noteに関する話題では、記事づくりや発信の工夫について具体的な会話がありました。")
        lines.append("書いたものを共有しながら、読み手に届きやすい形を一緒に考えられるのもF研らしい動きでした。")
    elif content_type == "money_consultation":
        hits = keyword_hits(texts, MONEY_KEYWORDS)
        if hits:
            lines.append("お金の話・相談では、" + "、".join(hits) + "など、F研らしい実務的な話題がありました。")
        else:
            lines.append("お金の話・相談では、資産形成やFIRE後の暮らし方について濃い会話がありました。")
        lines.append("単に資産を増やす話だけでなく、働き方や社会との関わり方まで話が広がるところが、このチャンネルらしいところです。")
        lines.append("数字の話と人生観の話が自然につながるので、FIREを目指す人にも、すでに次の暮らし方を考えている人にも読み応えのある会話になっていました。")
    elif content_type == "care_medical":
        hits = keyword_hits(texts, CARE_KEYWORDS)
        if hits:
            lines.append("介護・医療では、" + "、".join(hits) + "など、生活に近いテーマが話題になりました。")
        else:
            lines.append("介護・医療では、家族のケアや自分の体調との向き合い方について真剣な会話がありました。")
        lines.append("経験した人の言葉があることで、ひとりで抱え込みすぎないためのヒントも生まれていました。")
        lines.append("資産形成だけでは解決できない現実も、安心して相談できる場所があることはコミュニティの大事な価値だと感じます。")
    else:
        lines.append(f"{label}でも、メンバー同士の暮らしや関心が見える会話がありました。")
        lines.append("日々の小さな話題から交流が広がるのも、F研らしい動きでした。")

    if focus_paragraphs:
        lines.append("")
        lines.extend(focus_paragraphs)

    if topic_images.get(content_type):
        lines.extend(["", "画像候補:"])
        lines.extend(f"- {url}" for url in topic_images[content_type])

    lines.append("")
    return lines


def opener_lines(
    start: datetime,
    end: datetime,
    top_sections: list[str],
    post_topics: dict[str, list[dict[str, Any]]],
) -> list[str]:
    if start.year == end.year and start.month == end.month and start.day == 1 and end.day == 15:
        period_text = f"{start.month}月前半"
    elif start.year == end.year and start.month == end.month and start.day == 15 and start.hour == 12:
        period_text = f"{start.month}月後半"
    else:
        period_text = period_label(start, end)

    topic_labels = [POST_TYPE_LABELS.get(key, key) for key in post_topics]
    section_labels = [name.replace("・", "、") for name in top_sections[:3]]
    highlights = unique_preserve_order(section_labels + topic_labels[:4])
    travel_texts = [str(item.get("clean_content") or "") for item in post_topics.get("travel", [])]
    money_texts = [str(item.get("clean_content") or "") for item in post_topics.get("money_consultation", [])]
    book_texts = [str(item.get("clean_content") or "") for item in post_topics.get("book", [])]
    if has_any(travel_texts, ("ネパール", "カトマンズ", "ナガルコット", "ヒマラヤ", "エベレスト")):
        return [
            f"{period_text}のF研は、大きなイベントの数で押すというより、日々の会話の中に面白さが詰まっていた期間でした。",
            "",
            "本の話からこれからの暮らし方を考えたり、旅の話からネパール旅行の企画が立ち上がったり、お金の相談から家族への渡し方まで掘り下がったり。",
            "",
            "派手なニュースではないけれど、読んでいると「自分ならどうするかな」と考えたくなる話題がいくつもありました。",
            "",
        ]
    if has_any(money_texts, ("こどもNISA", "児童手当", "教育資金")) or has_any(book_texts, ("FIRE", "自由", "れんげ荘")):
        return [
            f"{period_text}のF研は、本、旅、お金の話を通じて、これからの暮らし方を考える会話が広がりました。",
            "",
            "単なる情報交換というより、自分ならどうするか、どんな毎日を送りたいかを考える材料があちこちにありました。",
            "",
        ]
    if highlights:
        return [
            f"{period_text}は、" + "、".join(highlights) + "など、いろいろなチャンネルで会話と交流が広がりました。",
            "",
            "大きなイベントだけでなく、ふとした相談や旅先の話、本の感想から話が広がっていくのもF研らしいところです。",
            "",
        ]
    return [
        f"{period_text}も、F研らしい会話と交流がありました。",
        "",
    ]


def render_draft(
    activities: list[Activity],
    post_topics: dict[str, list[dict[str, Any]]],
    section_images: dict[str, list[tuple[str, str | None]]],
    start: datetime,
    end: datetime,
    include_source_links: bool,
    max_activities_per_section: int,
    template: str,
    topic_images: dict[str, list[str]],
) -> str:
    label = period_label(start, end)
    sections: dict[str, list[Activity]] = defaultdict(list)
    for activity in activities:
        if is_public_sensitive_text(f"{activity.title}\n{activity.summary}"):
            continue
        sections[activity.source].append(activity)

    top_sections = [name for name, _ in SECTION_RULES if sections.get(name)]
    top_sections.extend(name for name in ("その他の動き",) if sections.get(name))
    highlighted_section = max(top_sections, key=lambda name: len(sections[name]), default="")
    travel_texts = [str(item.get("clean_content") or "") for item in post_topics.get("travel", [])]
    if has_any(travel_texts, ("ネパール", "カトマンズ", "ナガルコット", "ヒマラヤ", "エベレスト")):
        title_tail = "本と旅とお金の話から、暮らしの輪郭が見えてきました！"
    elif post_topics and start.day == 1 and end.day == 15:
        title_tail = "暮らしの話題とオンライン企画が広がりました！"
    elif highlighted_section:
        title_tail = EDITORIAL_TITLE_BY_SECTION.get(highlighted_section, "F研らしい動きがありました！")
    else:
        title_tail = "F研らしい話題が広がりました！"

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
        ]
        lines.extend(opener_lines(start, end, top_sections, post_topics))
        if show_internal_notes:
            lines.extend(
                [
                    "<!-- 編集メモ: 募集御礼、さいごに、宣伝などの固定セクションは必要な場合だけ追加してください。 -->",
                    "",
                ]
            )

    if top_sections and show_internal_notes:
        overview = "、".join(name.replace("・", "、") for name in top_sections)
        lines.extend([f"この期間も、{overview}など、F研らしくいろいろなことが同時多発的に進みました。", ""])

    if post_topics and template == "editorial":
        topic_order = ("book", "travel", "question_consultation", "note", "money_consultation", "care_medical", "parenting", "real_estate")
        for content_type in topic_order:
            if post_topics.get(content_type):
                lines.extend(render_topic_section(content_type, post_topics[content_type], topic_images))

    for section_name in top_sections:
        rendered_activities: list[str] = []
        section_activities = sections[section_name]
        for activity in section_activities[:max_activities_per_section]:
            rendered_activities.extend(render_activity(activity, include_source_links))
        if not rendered_activities:
            continue
        lines.extend([f"## {section_name}", ""])
        lines.extend(rendered_activities)
        omitted = len(section_activities) - max_activities_per_section
        if omitted > 0 and show_internal_notes:
            lines.extend([f"[編集メモ: このセクションには他に{omitted}件の候補があります。必要なら期間を短くするか、出力上限を増やしてください。]", ""])
        if show_internal_notes and section_images.get(section_name):
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
    elif template == "editorial":
        lines.extend(
            [
                "## さいごに",
                "",
                f"{label}は、本、旅、お金、相談、オンラインの交流など、いろいろな話題がありました。",
                "",
                "ただ並べてみると、どれも別々の話に見えて、根っこには「これからどう暮らすか」という問いがある気がします。",
                "",
                "どんな本を読むか。",
                "どこへ行くか。",
                "家族にどうお金を渡すか。",
                "初めての人が入りやすい場をどう作るか。",
                "自分の時間を何に使うか。",
                "",
                "FIREはゴールではなく、その後の暮らしを考えるための入口でもあります。",
                "",
                f"{label}のF研には、その入口から先の話がたくさんありました。",
            ]
        )
    elif show_internal_notes:
        lines.extend(
            [
                "<!-- 宣伝セクションは既存記事の固定文をコピーして、この下に貼れます。不要ならこのコメントごと削除してください。 -->",
            ]
        )
    return final_reader_cleanup("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a note activity report draft from Discord JSON.")
    period = parser.add_mutually_exclusive_group()
    period.add_argument("--month", help="Target month in YYYY-MM, JST.")
    period.add_argument("--last-days", type=int, help="Generate a draft for the last N days from now.")
    parser.add_argument("--start", help="Explicit start date/datetime. Requires --end.")
    parser.add_argument("--end", help="Explicit end date/datetime. Requires --start.")
    parser.add_argument(
        "--half",
        choices=("first", "second"),
        help="With --month, generate 1 00:00-15 12:00 or after 15 12:00-month-end 12:00 for the twice-a-month F研通信 cadence.",
    )
    parser.add_argument("--events-raw", default=DEFAULT_EVENT_RAW)
    parser.add_argument("--events-curated", default=DEFAULT_EVENT_CURATED)
    parser.add_argument("--posts-raw", default=DEFAULT_POSTS_RAW)
    parser.add_argument("--output", help="Output Markdown path. Defaults under tmp/note_drafts/.")
    parser.add_argument("--max-images-per-item", type=int, default=4)
    parser.add_argument("--max-section-images", type=int, default=8)
    parser.add_argument("--max-activities-per-section", type=int, default=8)
    parser.add_argument("--post-topic-limit", type=int, default=8)
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
        if args.half:
            raise SystemExit("--half can only be used with --month.")
        if not (args.start and args.end):
            raise SystemExit("--start and --end must be provided together.")
        start = parse_date(args.start)
        end = parse_date(args.end, end_of_day=True)
    elif args.month:
        start, end = month_half_range(args.month, args.half) if args.half else month_range(args.month)
    else:
        if args.half:
            raise SystemExit("--half can only be used with --month.")
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
    post_topics = collect_post_topics(posts_raw, start, end, args.post_topic_limit)
    section_images = collect_section_images(raw_events, start, end, args.max_section_images)
    topic_images = collect_topic_images(posts_raw, start, end, args.max_section_images)
    draft = render_draft(
        activities,
        post_topics,
        section_images,
        start,
        end,
        args.include_source_links,
        args.max_activities_per_section,
        args.template,
        topic_images,
    )

    if args.output:
        output = Path(args.output)
    elif args.month and args.half:
        output = Path(DEFAULT_OUTPUT_DIR) / f"fken-tsushin-{args.month}-{HALF_OUTPUT_SUFFIX[args.half]}-paste.md"
    else:
        output = Path(DEFAULT_OUTPUT_DIR) / f"fken-tsushin-{start:%Y-%m-%d}_{end:%Y-%m-%d}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft, encoding="utf-8")
    print(f"Wrote {output} ({len(activities)} activities, {sum(len(v) for v in post_topics.values())} topic candidates).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
