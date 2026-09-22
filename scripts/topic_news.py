"""タグ値ごとの関連ニュース取得(ゆるトーク画面の補助情報)。

GoogleニュースのRSS検索を、信頼できる報道系サイトに絞って叩くだけの軽量な
実装(専用のニュースAPIキーは使わない)。ゆるマッチングの開催間隔は概ね1か月
以内(かずさんの判断、2026-09-23)なので鮮度への要求は緩く、
topic_news_cache に14日キャッシュして同じタグの再取得を避ける。

投資助言に見える見出しを避けるため、ソースは一次報道系(NHK・日経・Reuters・
東洋経済オンライン・ダイヤモンドオンライン)だけに絞っている。該当記事が
見つからなければ空リストを返すだけで、フォールバックの一般ニュース検索は
しない(コミュニティのお金の話題で出所不明な記事を出さないため)。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = "fire-community-map-topic-news/0.1"
NEWS_CACHE_MAX_AGE_DAYS = 14
MAX_ARTICLES_PER_TAG = 3

# 一次報道系のみ。コミュニティのお金の話題で出所不明・扇動的な記事を出さないための絞り込み。
TRUSTED_NEWS_DOMAINS = [
    "nhk.or.jp",
    "nikkei.com",
    "reuters.com",
    "toyokeizai.net",
    "diamond.jp",
]

# ニュース検索の対象にするタグカテゴリ。mbti/fire_status のような短い記号的な
# 値(例: "INTJ")はニュース検索に向かないため対象外にしている。
NEWS_ELIGIBLE_CATEGORIES = {"interest", "chat_topic", "investment_style", "affiliation"}


def _google_news_rss_url(tag_value: str) -> str:
    site_filter = " OR ".join(f"site:{domain}" for domain in TRUSTED_NEWS_DOMAINS)
    query = f"{tag_value} ({site_filter})"
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ja&gl=JP&ceid=JP:ja"


def _parse_rss_items(raw_xml: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_xml)
    articles = []
    for item in root.findall("./channel/item")[:MAX_ARTICLES_PER_TAG]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        articles.append({"title": title, "url": link, "source": source, "published_at": pub_date})
    return articles


def fetch_news_for_tag(tag_value: str) -> list[dict[str, Any]]:
    """信頼できる報道系サイトに絞ったGoogleニュースRSS検索を叩き、記事を最大3件返す。

    ネットワークエラーやパース失敗はベストエフォートの補助機能として握りつぶし、
    空リストを返す(ニュース取得の失敗でマッチングバッチ全体を落とさないため)。
    """
    req = Request(_google_news_rss_url(tag_value), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as res:
            return _parse_rss_items(res.read())
    except (HTTPError, URLError, ET.ParseError) as exc:
        print(f"  (topic_news) failed to fetch news for tag '{tag_value}': {exc}")
        return []


def _cache_get(supabase_url: str, service_role_key: str, tag_value: str) -> dict[str, Any] | None:
    headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
    req = Request(
        f"{supabase_url}/rest/v1/topic_news_cache?tag_value=eq.{quote(tag_value)}&select=articles,fetched_at",
        headers=headers,
        method="GET",
    )
    with urlopen(req, timeout=30) as res:
        rows = json.loads(res.read().decode("utf-8"))
    return rows[0] if rows else None


def _cache_put(supabase_url: str, service_role_key: str, tag_value: str, articles: list[dict[str, Any]]) -> None:
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    body = json.dumps([{
        "tag_value": tag_value,
        "articles": articles,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }]).encode("utf-8")
    req = Request(
        f"{supabase_url}/rest/v1/topic_news_cache?on_conflict=tag_value",
        data=body,
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=30) as res:
        res.read()


def get_or_fetch_topic_news(
    supabase_url: str,
    service_role_key: str,
    tag_value: str,
) -> list[dict[str, Any]]:
    """タグ値のニュースをキャッシュ優先で返す。キャッシュが14日以内ならそれを使い、なければRSSを取得してキャッシュする。"""
    try:
        cached = _cache_get(supabase_url, service_role_key, tag_value)
    except (HTTPError, URLError) as exc:
        print(f"  (topic_news) cache lookup failed for tag '{tag_value}': {exc}")
        cached = None

    if cached:
        fetched_at = datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - fetched_at < timedelta(days=NEWS_CACHE_MAX_AGE_DAYS):
            return cached.get("articles") or []

    articles = fetch_news_for_tag(tag_value)
    try:
        _cache_put(supabase_url, service_role_key, tag_value, articles)
    except (HTTPError, URLError) as exc:
        print(f"  (topic_news) cache write failed for tag '{tag_value}': {exc}")
    return articles
