#!/usr/bin/env python3
"""Apply low-risk event candidate supplements to curated event JSON.

This intentionally handles only narrow, repeatable cases:

- the Discord message belongs to a thread that already has a curated event
- the message text contains a recognized operational update

Anything else stays in the review issue.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from build_event_review_report import build_report, read_json


JST = timezone(timedelta(hours=9))


def discord_thread_id(permalink: str | None) -> str | None:
    if not permalink:
        return None
    parts = str(permalink).rstrip("/").split("/")
    if len(parts) >= 3 and parts[-3] == "channels":
        return None
    if len(parts) >= 2:
        return parts[-2]
    return None


def event_keys(event: dict[str, Any]) -> set[str]:
    keys = set()
    message_id = str(event.get("discord_message_id") or "")
    if message_id:
        keys.add(message_id)
    thread_id = discord_thread_id(event.get("discord_permalink"))
    if thread_id:
        keys.add(thread_id)
    return keys


def normalize(text: str) -> str:
    return " ".join(str(text or "").split())


def set_if_changed(event: dict[str, Any], key: str, value: Any) -> bool:
    if event.get(key) == value:
        return False
    event[key] = value
    return True


def apply_known_supplement(event: dict[str, Any], item: dict[str, Any]) -> list[str]:
    """Return human-readable applied changes."""
    text = normalize(f"{item.get('thread_name') or ''} {item.get('content') or ''}")
    changes: list[str] = []

    if "那須ハイランド" in str(event.get("title") or "") and re.search(r"運行予定機種|ビッグバーン|XDダークライド|F²|F2", text):
        note = (
            "10/25で日程確定・貸切予約済み。最初で最後の遊園地貸し切りオフ会。"
            "絶叫プランはF²をビッグバーンコースターへ変更し、VRライドシアター XDダークライドと合わせて希望を出す方向。"
            "天候や日没条件が厳しい場合はF²へ戻す可能性あり。宿泊するか日帰りかは各自選択。"
        )
        summary = (
            "株主優待を利用して、一般営業終了後の2時間で那須ハイランドパークを貸し切るオフ会。"
            "子ども連れ参加も想定。日本駐車場開発の株主優待変更により、貸切利用は今回が最初で最後になる可能性がある。"
            "運行予定機種はビッグバーンコースターとVRライドシアター XDダークライドを軸に調整している。"
        )
        if set_if_changed(event, "participation_note", note):
            changes.append("運行予定機種の希望内容を participation_note に反映")
        if set_if_changed(event, "summary", summary):
            changes.append("運行予定機種の概要を summary に反映")
        if not changes:
            changes.append("運行予定機種の補足は既に反映済み")

    if "葉山オフ会" in str(event.get("title") or "") and re.search(r"天気|天候|プランB|ホームパーティー|手巻き|割り勘|持ち寄り", text):
        if set_if_changed(event, "title", "9/29 葉山オフ会（手巻きパーティー）"):
            changes.append("タイトルを手巻きパーティーへ更新")
        if set_if_changed(event, "tags", ["オフ会", "神奈川", "手巻きパーティー", "葉山"]):
            changes.append("タグを手巻きパーティー前提に更新")
        if set_if_changed(event, "location_label", "葉山（Champagne Bar Ingalleonのバースペース）"):
            changes.append("会場をバースペースへ更新")
        note = (
            "スレ主のみかんさん、たびおさん、Aki、閣下さんらが参加予定。"
            "天候悪化見込みのため海岸BBQからバースペースでのホームパーティー形式に変更し、"
            "飲み物と手巻きの準備をベースに、持ち寄りも併用する予定。"
            "購入品は申告して最後に合算・割り勘にする案。"
        )
        summary = (
            "神奈川県葉山でのオフ会。天候を踏まえ、当初の海岸BBQからChampagne Bar Ingalleonの"
            "バースペースでの手巻きパーティーへプランBに切り替える予定。持ち寄りも交えながら交流する。"
        )
        if set_if_changed(event, "participation_note", note):
            changes.append("雨天代替プランを participation_note に反映")
        if set_if_changed(event, "summary", summary):
            changes.append("雨天代替プランを summary に反映")
        if not changes:
            changes.append("雨天代替プランの補足は既に反映済み")

    return changes


def write_pr_body(path: Path, applied: list[dict[str, Any]], remaining_count: int) -> None:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    lines = [
        "## 自動レビュー結果",
        "",
        f"{today} のイベント候補から、既存 curated イベントへ安全に紐づく補足だけを反映しました。",
        "",
        "## 反映した内容",
        "",
    ]
    if applied:
        for item in applied:
            lines.extend(
                [
                    f"- `{item['title']}`",
                    f"  - Discord: {item['discord_permalink']}",
                    f"  - 反映: {'、'.join(item['changes'])}",
                ]
            )
    else:
        lines.append("- なし")
    lines.extend(
        [
            "",
            "## 反映しなかった内容",
            "",
            f"- 自動判断できない候補: {remaining_count} 件",
            "- 新規イベント作成、参加人数の推定、場所未確定の判断は人間レビューに残します。",
            "",
            "## 確認",
            "",
            "- `python3 -m json.tool data/community_events_curated.json`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-apply safe event candidate supplements.")
    parser.add_argument("--raw", default="tmp/community_events_raw.json")
    parser.add_argument("--curated", default="data/community_events_curated.json")
    parser.add_argument("--applied-message-ids-output", default="tmp/community_events_auto_applied_message_ids.json")
    parser.add_argument("--pr-body-output", default="tmp/community_events_auto_review_pr_body.md")
    parser.add_argument("--summary-output", default="tmp/community_events_auto_review_summary.json")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--lookback-hours", type=float, default=26)
    parser.add_argument("--min-score", type=int, default=3)
    args = parser.parse_args()

    raw = read_json(Path(args.raw), [])
    curated = read_json(Path(args.curated), [])
    if not isinstance(raw, list):
        raise SystemExit(f"{args.raw} must contain a JSON array.")
    if not isinstance(curated, list):
        raise SystemExit(f"{args.curated} must contain a JSON array.")

    _, report = build_report(raw, curated, args.limit, args.lookback_hours, args.min_score)
    candidate_titles = {
        line[3:].strip()
        for line in report.splitlines()
        if line.startswith("## ") and re.match(r"## \d+\. ", line)
    }

    by_key: dict[str, dict[str, Any]] = {}
    for event in curated:
        for key in event_keys(event):
            by_key[key] = event

    applied: list[dict[str, Any]] = []
    applied_ids: list[str] = []
    remaining_count = 0

    for item in raw:
        title = str(item.get("thread_name") or "").strip() or normalize(item.get("content") or "")[:48]
        numbered_title = next((candidate for candidate in candidate_titles if candidate.endswith(title)), None)
        if not numbered_title:
            continue
        message_id = str(item.get("discord_message_id") or "")
        thread_id = discord_thread_id(item.get("discord_permalink"))
        event = by_key.get(thread_id or "")
        if not event:
            remaining_count += 1
            continue
        changes = apply_known_supplement(event, item)
        if changes:
            applied_ids.append(message_id)
            applied.append(
                {
                    "title": event.get("title") or title,
                    "discord_permalink": item.get("discord_permalink"),
                    "changes": changes,
                }
            )
        else:
            remaining_count += 1

    Path(args.applied_message_ids_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.applied_message_ids_output).write_text(json.dumps(applied_ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_pr_body(Path(args.pr_body_output), applied, remaining_count)
    Path(args.summary_output).write_text(
        json.dumps({"applied": applied, "remaining_count": remaining_count}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if applied:
        Path(args.curated).write_text(json.dumps(curated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Auto-applied event candidate supplements: {len(applied)}")
    print(f"Remaining event candidates for human review: {remaining_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
