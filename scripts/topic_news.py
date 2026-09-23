"""タグ値ごとの関連記事取得(ゆるトーク画面の補助情報)。

GoogleニュースのRSS検索を叩くだけの軽量な実装(専用のニュースAPIキーは使わない)。
ゆるマッチングの開催間隔は概ね1か月以内(かずさんの判断、2026-09-23)なので
鮮度への要求は緩く、topic_news_cache に14日キャッシュして同じタグの再取得を避ける。

カテゴリごとに検索方針を分けている(かずさんのフィードバック、2026-09-23):
- investment_style/affiliation はお金の話題なので、投資助言に見える見出しを避けたい。
  信頼できる報道系サイト(TRUSTED_NEWS_DOMAINS)に絞った検索を優先し、それだけでは
  MIN_ARTICLES_PER_TAG件に届かない場合のみサイト縛りなしの一般検索で補う。
- interest/chat_topic は趣味・雑談の話題なので、経済メディア縛りだと「話題のきっかけ」
  として物足りない(そもそも記事が少ない/固すぎる)。最初から一般検索のみを使い、
  ニュースに限らずブログ・コラムなども含めて幅広く記事を拾う。

どちらの経路でも、複数の候補記事は公開日時が新しい順に並べて上位を採用する
(「できるだけタイムリーなニュースを表示したい」というフィードバック、2026-09-23)。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = "fire-community-map-topic-news/0.1"
NEWS_CACHE_MAX_AGE_DAYS = 14
MAX_ARTICLES_PER_TAG = 3
# 信頼ソース(投資関連カテゴリ)でこれ未満しか見つからない場合、サイト縛りなしの
# 一般検索で補う(0件表示を避ける)。
MIN_ARTICLES_PER_TAG = 2

# 一次報道系を中心に、コミュニティのお金の話題で出所不明・扇動的な記事を出さないための
# 絞り込み。件数を確保しやすいよう主要な全国紙・経済メディアも加えている。
# investment_style/affiliation タグにのみ使う(下記 TRUSTED_SOURCE_CATEGORIES)。
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

# 記事検索の対象にするタグカテゴリ。mbti/fire_status のような短い記号的な値
# (例: "INTJ")は検索に向かないため対象外にしている(build_common_tags側でも除外)。
NEWS_ELIGIBLE_CATEGORIES = {"interest", "chat_topic", "investment_style", "affiliation"}

# お金の話題(投資助言っぽく見えないよう信頼できる報道系サイトを優先したい)。
# それ以外(interest/chat_topic)は経済メディア縛りだと記事が少なすぎたり固すぎたりするため、
# 最初から一般検索のみを使い、ニュースに限らず幅広く「面白そうな記事」を拾う。
TRUSTED_SOURCE_CATEGORIES = {"investment_style", "affiliation"}


def _google_news_rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ja&gl=JP&ceid=JP:ja"


def _parse_pub_date(pub_date: str) -> datetime | None:
    if not pub_date:
        return None
    try:
        parsed = parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_rss_items(raw_xml: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw_xml)
    articles = []
    # 呼び出し側(fetch_news_for_tag)で新しい順に並べ替えてから絞り込むので、
    # ここではMAX_ARTICLES_PER_TAGより少し多め(8件)まで拾っておく。
    for item in root.findall("./channel/item")[:8]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        published_dt = _parse_pub_date(pub_date)
        articles.append({
            "title": title,
            "url": link,
            "source": source,
            "published_at": published_dt.isoformat() if published_dt else None,
        })
    return articles


def _fetch_rss_articles(query: str) -> list[dict[str, Any]]:
    req = Request(_google_news_rss_url(query), headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as res:
            return _parse_rss_items(res.read())
    except (HTTPError, URLError, ET.ParseError) as exc:
        print(f"  (topic_news) failed to fetch news for query '{query}': {exc}")
        return []


def _sort_by_recency(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """公開日時が新しい順。日時が取れなかった記事は末尾に回す(0件を避けるため
    捨てずに残すが、鮮度がわかる記事を優先したい)。"""
    def sort_key(article: dict[str, Any]) -> str:
        return article["published_at"] or ""

    return sorted(articles, key=sort_key, reverse=True)


def fetch_news_for_tag(tag_value: str, category: str) -> list[dict[str, Any]]:
    """タグ値の関連記事を、公開日時が新しい順に最大MAX_ARTICLES_PER_TAG件返す。

    investment_style/affiliation(お金の話題)は投資助言に見える記事を避けたいので、
    信頼できる報道系サイトに絞った検索を優先し、それだけではMIN_ARTICLES_PER_TAG件に
    届かない場合のみサイト縛りなしの一般検索で補う。それ以外(interest/chat_topic)は
    経済メディア縛りだと記事が少なすぎたり固すぎたりするため、最初から一般検索のみを使う
    (「ニュースに限らず幅広く面白そうな記事を」というフィードバック、2026-09-23)。

    ネットワークエラーやパース失敗はベストエフォートの補助機能として握りつぶし、
    その時点までに集まった分(空リストのこともある)を返す(記事取得の失敗で
    マッチングバッチ全体を落とさないため)。
    """
    articles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    def _add(candidates: list[dict[str, Any]]) -> None:
        # Google Newsの検索結果は同じ記事が別URL(異なる配信元ミラー)で重複して
        # 返ってくることがあるため、URLだけでなくタイトルでも重複除去する。
        for article in _sort_by_recency(candidates):
            if len(articles) >= MAX_ARTICLES_PER_TAG or article["title"] in seen_titles:
                continue
            articles.append(article)
            seen_titles.add(article["title"])

    if category in TRUSTED_SOURCE_CATEGORIES:
        site_filter = " OR ".join(f"site:{domain}" for domain in TRUSTED_NEWS_DOMAINS)
        _add(_fetch_rss_articles(f"{tag_value} ({site_filter})"))
        if len(articles) < MIN_ARTICLES_PER_TAG:
            _add(_fetch_rss_articles(tag_value))
    else:
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
    category: str,
) -> list[dict[str, Any]]:
    """タグ値の関連記事をキャッシュ優先で返す。キャッシュが14日以内ならそれを使い、なければ
    RSSを取得してキャッシュする。"""
    try:
        cached = _cache_get(supabase_url, service_role_key, tag_value)
    except (HTTPError, URLError) as exc:
        print(f"  (topic_news) cache lookup failed for tag '{tag_value}': {exc}")
        cached = None

    if cached:
        fetched_at = datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - fetched_at < timedelta(days=NEWS_CACHE_MAX_AGE_DAYS):
            return cached.get("articles") or []

    articles = fetch_news_for_tag(tag_value, category)
    try:
        _cache_put(supabase_url, service_role_key, tag_value, articles)
    except (HTTPError, URLError) as exc:
        print(f"  (topic_news) cache write failed for tag '{tag_value}': {exc}")
    return articles
