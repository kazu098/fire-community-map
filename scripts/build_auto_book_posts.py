#!/usr/bin/env python3
"""Build auto-curated community book posts from raw Discord messages.

This deliberately avoids LLM/API summarization. It only auto-curates posts
where a book title can be extracted from text and the poster maps to an
existing member profile. Ambiguous posts stay out of the output so the review
Issue remains the exception queue.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BOOK_TITLE_PATTERNS = [
    re.compile(r"『([^』]{2,80})』"),
    re.compile(r"【([^】]{2,80})】"),
    re.compile(r"「([^」]{2,80})」"),
]
BOOK_HINT_RE = re.compile(r"(読了|読みました|読んだ|一気読み|おすすめ|紹介|著|Kindle|Audible|オーディブル|漫画|小説|本)")
LOW_VALUE_RE = re.compile(r"^(ありがとうございます|ありがとう|読んでみます|買いました|購入しました|気になります|面白いですよね)[！!。😊☺️]*$")
URL_RE = re.compile(r"https?://\S+")


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact(text: str) -> str:
    return " ".join(text.split())


def strip_urls(text: str) -> str:
    return URL_RE.sub("", text)


def known_message_ids(*collections: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for collection in collections:
        ids.update(str(item["discord_message_id"]) for item in collection if item.get("discord_message_id"))
    return ids


def supabase_request(method: str, url: str, service_role_key: str) -> Any:
    req = Request(
        url,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(req, timeout=30) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase API error {exc.code} for {method} {url}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase API request failed for {method} {url}: {exc}") from exc


def fetch_known_nicknames(env_file: Path) -> set[str] | None:
    load_dotenv(env_file)
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        return None
    rows = supabase_request("GET", f"{supabase_url}/rest/v1/member_profiles?select=nickname", service_role_key)
    return {str(row["nickname"]) for row in (rows or []) if row.get("nickname")}


def fetch_remote_book_ids(env_file: Path) -> set[str]:
    load_dotenv(env_file)
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_role_key:
        return set()
    rows = supabase_request(
        "GET",
        f"{supabase_url}/rest/v1/community_posts?select=discord_message_id&content_type=eq.book",
        service_role_key,
    )
    return {str(row["discord_message_id"]) for row in (rows or []) if row.get("discord_message_id")}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def title_from_text(text: str) -> str | None:
    clean = strip_urls(text)
    lines = [compact(line) for line in clean.splitlines() if compact(line)]
    for line in lines:
        quoted_line = re.match(r"^[『【]([^』】]{2,80})[』】](?:\s+.+)?$", line)
        if quoted_line:
            title = compact(quoted_line.group(1))
            if not looks_like_non_title_quote(title):
                return title

    for pattern in BOOK_TITLE_PATTERNS:
        for match in pattern.finditer(clean):
            title = compact(match.group(1))
            start = max(0, match.start() - 32)
            end = min(len(clean), match.end() + 32)
            left_context = clean[start:match.start()]
            right_context = clean[match.end():end]
            immediate_right = right_context[:16]
            has_title_marker = bool(
                re.search(r"(という本|という漫画|読了|読みました|読んだ|一気読み|おすすめ)", immediate_right)
            )
            if has_title_marker and not looks_like_non_title_quote(title):
                return title

    for index, line in enumerate(lines):
        if len(line) > 60 or BOOK_HINT_RE.search(line):
            continue
        if re.search(r"[0-9０-９、,・←:：]", line):
            continue
        if any(mark in line for mark in ("。", "！", "？", "です", "ます", "<@", "さん")):
            continue
        prev_line = lines[index - 1] if index > 0 else ""
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        is_near_link = bool(URL_RE.search(prev_line) or URL_RE.search(next_line))
        looks_like_title_author = bool(re.search(r"[ぁ-んァ-ヶ一-龠]{2,}\s+[ぁ-んァ-ヶ一-龠A-Za-z・ー]{2,}$", line))
        if (is_near_link or looks_like_title_author) and re.search(r"[ぁ-んァ-ヶ一-龠A-Za-z0-9]", line):
            return line
    return None


def looks_like_non_title_quote(value: str) -> bool:
    return bool(re.search(r"(とは|という|どなたか|幸せ|世界|世間|行きたい|おすすめ)", value))


def summary_for(title: str, text: str) -> str:
    clean = compact(strip_urls(text))
    clean = clean.replace(f"『{title}』", "").replace(f"「{title}」", "").replace(f"【{title}】", "")
    clean = compact(clean)
    if len(clean) > 140:
        clean = clean[:139] + "…"
    if clean:
        return f"{title}について、投稿者が「{clean}」として紹介した読書投稿。"
    return f"{title}について紹介された読書投稿。"


def rejection_reason(item: dict[str, Any], known_nicknames: set[str] | None) -> str | None:
    if item.get("content_type") != "book":
        return "not_book"
    text = str(item.get("content") or "")
    clean = compact(strip_urls(text))
    if len(clean) < 20 or LOW_VALUE_RE.match(clean):
        return "short_or_reply"
    if not BOOK_HINT_RE.search(clean):
        return "no_book_hint"
    title = title_from_text(text)
    if not title:
        return "title_not_found"
    nickname = str(item.get("member_nickname") or "").strip()
    if known_nicknames is None:
        return "known_member_check_unavailable"
    if not nickname or nickname not in known_nicknames:
        return "member_not_mapped"
    return None


def build_auto_posts(
    raw: list[dict[str, Any]],
    curated: list[dict[str, Any]],
    remote_book_ids: set[str],
    known_nicknames: set[str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen = known_message_ids(curated) | remote_book_ids
    auto_posts: list[dict[str, Any]] = []
    review_posts: list[dict[str, Any]] = []

    for item in sorted(raw, key=lambda row: str(row.get("posted_at") or ""), reverse=True):
        message_id = str(item.get("discord_message_id") or "")
        if not message_id or message_id in seen:
            continue
        if item.get("content_type") != "book":
            continue
        reason = rejection_reason(item, known_nicknames)
        if reason:
            review_posts.append({**item, "auto_rejection_reason": reason})
            continue
        title = title_from_text(str(item.get("content") or ""))
        if not title:
            review_posts.append({**item, "auto_rejection_reason": "title_not_found"})
            continue
        auto_posts.append(
            {
                "discord_message_id": message_id,
                "channel_name": item["channel_name"],
                "content_type": "book",
                "title": title,
                "summary": summary_for(title, str(item.get("content") or "")),
                "discord_author_display_name": item.get("discord_author_display_name"),
                "member_nickname": item.get("member_nickname"),
                "posted_at": item["posted_at"],
                "discord_permalink": item["discord_permalink"],
            }
        )

    return auto_posts, review_posts


def render_review(review_posts: list[dict[str, Any]]) -> str:
    labels = {
        "short_or_reply": "短文・返信寄りのため自動反映しませんでした。",
        "no_book_hint": "本紹介と判断する語が弱いため自動反映しませんでした。",
        "title_not_found": "本文から本タイトルを確定できませんでした。",
        "member_not_mapped": "投稿者が member_profiles に一致しませんでした。",
        "known_member_check_unavailable": "member_profiles の確認ができませんでした。",
    }
    lines = [
        "# 読書投稿の自動反映例外",
        "",
        f"例外件数: {len(review_posts)}",
        "",
    ]
    for index, item in enumerate(review_posts, 1):
        reason = str(item.get("auto_rejection_reason") or "unknown")
        lines.extend(
            [
                f"## {index}. {labels.get(reason, reason)}",
                "",
                f"- 投稿者: `{item.get('member_nickname') or item.get('discord_author_display_name') or 'unknown'}`",
                f"- 投稿日: `{item.get('posted_at')}`",
                f"- Discord: {item.get('discord_permalink')}",
                "",
                "```text",
                compact(item.get("content") or "")[:700],
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build auto-curated book posts.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--raw", default="tmp/community_posts_raw.json")
    parser.add_argument("--curated", default="tmp/community_posts_curated.json")
    parser.add_argument("--output", default="tmp/community_posts_book_auto.json")
    parser.add_argument("--review-output", default="tmp/community_posts_book_review_needed.md")
    parser.add_argument("--count-output", default="tmp/community_posts_book_auto_count.txt")
    parser.add_argument("--review-count-output", default="tmp/community_posts_book_review_count.txt")
    args = parser.parse_args()

    raw = read_json(Path(args.raw), [])
    curated = read_json(Path(args.curated), [])
    if not isinstance(raw, list):
        raise SystemExit(f"{args.raw} must contain a JSON array.")
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")

    known_nicknames = fetch_known_nicknames(Path(args.env_file))
    remote_book_ids = fetch_remote_book_ids(Path(args.env_file))
    auto_posts, review_posts = build_auto_posts(raw, curated, remote_book_ids, known_nicknames)

    write_json(Path(args.output), auto_posts)
    Path(args.count_output).write_text(str(len(auto_posts)), encoding="utf-8")
    review_path = Path(args.review_output)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(render_review(review_posts) + "\n", encoding="utf-8")
    Path(args.review_count_output).write_text(str(len(review_posts)), encoding="utf-8")

    print(f"Auto-curated book posts: {len(auto_posts)}")
    print(f"Book posts needing review: {len(review_posts)}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
