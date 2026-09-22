"""タグ値ごとの関連ニュース取得(ゆるトーク画面の補助情報)。

GoogleニュースのRSS検索を、信頼できる報道系サイトに絞って叩くだけの軽量な
実装(専用のニュースAPIキーは使わない)。ゆるマッチングの開催間隔は概ね1か月
以内(かずさんの判断、2026-09-23)なので鮮度への要求は緩く、
topic_news_cache に14日キャッシュして同じタグの再取得を避ける。

投資助言に見える見出しを避けるため、まずは信頼できる報道系サイト(TRUSTED_NEWS_DOMAINS)
に絞って検索する。ただしタグによっては絞り込みだけでは0〜1件しか見つからず、
「話題のきっかけ」として物足りないため(かずさんのフィードバック、2026-09-23)、
MIN_ARTICLES_PER_TAG件に満たない場合はサイト縛りなしの一般検索で不足分を補う
2段階構成にしている。信頼ソース側の記事を優先して並べ、一般検索の記事は
ソース名を表示するのでどちらの経路か画面上でも区別できる。
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
# これ未満しか信頼ソースで見つからない場合、サイト縛りなしの一般検索で補う(0件表示を避ける)。
MIN_ARTICLES_PER_TAG = 2

# 一次報道系を中心に、コミュニティのお金の話題で出所不明・扇動的な記事を出さないための
# 絞り込み。件数を確保しやすいよう主要な全国紙・経済メディアも加えている。
TRUSTED_NEWS_DOMAINS = [
    "nhk.or.jp",
    "nikkei.com",
    "reuters.com",
    "toyokeizai.net",
    "diamond.jp",
    "asahi.com",
    "yomiuri.co.jp",
    "mainichi.jp",
    "itmedia.co.jp",
    "businessinsider.jp",
    "forbesjapan.com",
]

# ニュース検索の対象にするタグカテゴリ。mbti/fire_status のような短い記号的な
# 値(例: "INTJ")はニュース検索に向かないため対象外にしている。
NEWS_ELIGIBLE_CATEGORIES = {"interest", "chat_topic", "investment_style", "affiliation"}


def _google_news_rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ja&gl=JP&ceid=JP:ja"


def _parse_rss_items(raw_xml: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_xml)
    articles = []
    # 呼び出し側(fetch_news_for_tag)で信頼ソース分と一般検索分を合わせて絞り込むので、
    # ここではMAX_ARTICLES_PER_TAGより少し多め(6件)まで拾っておく。
    for item in root.findall("./channel/item")[:6]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        articles.append({"title": title, "url": link, "source": source, "published_at": pub_date})
    return articles


def _fetch_rss_articles(query: str) -> list[dict[str, Any]]:
    req = Request(_google_news_rss_url(query), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as res:
            return _parse_rss_items(res.read())
    except (HTTPError, URLError, ET.ParseError) as exc:
        print(f"  (topic_news) failed to fetch news for query '{query}': {exc}")
        return []


def fetch_news_for_tag(tag_value: str) -> list[dict[str, Any]]:
    """タグ値のニュースを最大MAX_ARTICLES_PER_TAG件返す。

    まず信頼できる報道系サイトに絞ったGoogleニュースRSS検索を叩く。それだけでは
    MIN_ARTICLES_PER_TAG件に届かない場合(「0件」がきっかけとして物足りないという
    フィードバック、2026-09-23)、サイト縛りなしの一般検索で不足分を補う。
    信頼ソース分を優先して並べ、一般検索分は末尾に追加する。

    ネットワークエラーやパース失敗はベストエフォートの補助機能として握りつぶし、
    その時点までに集まった分(空リストのこともある)を返す(ニュース取得の失敗で
    マッチングバッチ全体を落とさないため)。
    """
    site_filter = " OR ".join(f"site:{domain}" for domain in TRUSTED_NEWS_DOMAINS)

    articles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    def _add(candidates: list[dict[str, Any]]) -> None:
        # Google Newsの検索結果は同じ記事が別URL(異なる配信元ミラー)で重複して
        # 返ってくることがあるため、URLだけでなくタイトルでも重複除去する。
        for article in candidates:
            if len(articles) >= MAX_ARTICLES_PER_TAG or article["title"] in seen_titles:
                continue
            articles.append(article)
            seen_titles.add(article["title"])

    _add(_fetch_rss_articles(f"{tag_value} ({site_filter})"))
    if len(articles) < MIN_ARTICLES_PER_TAG:
        _add(_fetch_rss_articles(tag_value))

    return articles


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
