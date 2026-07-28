#!/usr/bin/env python3
"""Build a GitHub Issue-ready report for event candidates needing review."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EVENT_HINT_RE = re.compile(
    r"(開催|参加|募集|オフ会|イベント|オンライン|日時|場所|集合|予約|締切|リマインド|本日|明日|[0-9０-９]{1,2}[月/][0-9０-９]{1,2})",
    re.IGNORECASE,
)

CHANNEL_REVIEW_NAMES = {
    "オンラインイベント",
    "オフ会",
    "イベント用フォーラム",
    "1周年記念オフ会",
    "イタリアンオフ会",
    "9月13日-文学フリマ大阪",
}


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def already_curated_ids(curated: list[dict[str, Any]]) -> set[str]:
    return {str(item["discord_message_id"]) for item in curated if item.get("discord_message_id")}


def candidate_score(item: dict[str, Any]) -> int:
    text = f"{item.get('thread_name') or ''}\n{item.get('content') or ''}"
    score = 0
    for word in ("@everyone", "日時", "場所", "参加", "募集", "締切", "開催", "オフ会", "リマインド"):
        if word in text:
            score += 1
    if re.search(r"[0-9０-９]{1,2}[月/][0-9０-９]{1,2}", text):
        score += 2
    return score


def truncate(text: str, limit: int = 280) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


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


def build_report(
    raw: list[dict[str, Any]],
    curated: list[dict[str, Any]],
    limit: int,
    lookback_days: int,
    min_score: int,
) -> tuple[int, str]:
    curated_ids = already_curated_ids(curated)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    candidates = []
    for item in raw:
        if item.get("source_type") == "scheduled_event":
            continue
        posted_at = parse_posted_at(item.get("posted_at"))
        if posted_at is None or posted_at < cutoff:
            continue
        message_id = str(item.get("discord_message_id") or "")
        if not message_id or message_id in curated_ids:
            continue
        channel_name = str(item.get("channel_name") or "")
        if channel_name not in CHANNEL_REVIEW_NAMES:
            continue
        text = f"{item.get('thread_name') or ''}\n{item.get('content') or ''}"
        if not EVENT_HINT_RE.search(text):
            continue
        score = candidate_score(item)
        if score < min_score:
            continue
        candidates.append((score, item))

    candidates.sort(key=lambda pair: (pair[0], pair[1].get("posted_at") or ""), reverse=True)
    candidates = candidates[:limit]
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# イベント候補の確認が必要です - {today}",
        "",
        "Discordのイベント系チャンネルから、まだcuratedデータに入っていない候補を検出しました。",
        "内容を確認し、必要なものだけ `data/community_events_curated.json` またはSupabaseの `community_events` に反映してください。",
        "",
        f"対象期間: 直近{lookback_days}日",
        f"候補件数: {len(candidates)}",
        "",
    ]
    for i, (score, item) in enumerate(candidates, 1):
        title = item.get("thread_name") or truncate(item.get("content") or "無題", 48)
        lines.extend(
            [
                f"## {i}. {title}",
                "",
                f"- チャンネル: `{item.get('channel_name')}`",
                f"- 投稿日: `{item.get('posted_at')}`",
                f"- スコア: `{score}`",
                f"- Discord: {item.get('discord_permalink')}",
                "",
                "```text",
                truncate(item.get("content") or "", 500),
                "```",
                "",
            ]
        )
    return len(candidates), "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build event review-needed report.")
    parser.add_argument("--raw", default="tmp/community_events_raw.json")
    parser.add_argument("--curated", default="data/community_events_curated.json")
    parser.add_argument("--output", default="tmp/community_events_review_needed.md")
    parser.add_argument("--count-output", default="tmp/community_events_review_count.txt")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=3)
    args = parser.parse_args()

    raw = read_json(Path(args.raw), [])
    curated = read_json(Path(args.curated), [])
    if not isinstance(raw, list):
        raise SystemExit(f"{args.raw} must contain a JSON array.")
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")

    count, report = build_report(raw, curated, args.limit, args.lookback_days, args.min_score)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")
    Path(args.count_output).write_text(str(count), encoding="utf-8")
    print(f"Review-needed candidates: {count}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
