#!/usr/bin/env python3
"""レビュー済みの「この人に聞いてみたい」をmember_conversation_hooksへupsertする。

入力JSON(既定: tmp/conversation_hooks.json)の形:
  {"かず": [{"text": "こどもNISAの積立方針、どうやって決めた？", "basis": "note「…」(2026-10-12)"}], ...}
ファイルに載っているメンバーだけを洗い替えする(載っていないメンバーの行は触らない)。
下書きはClaude Code(サブスクの範囲内)で作り、かずさんのレビュー後に流す想定。LLM APIは使わない。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fetch_community_posts import load_dotenv, require_env

MAX_HOOK_CHARS = 60  # 告知の1行に収まる長さ


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert reviewed conversation hooks for ゆるマッチング.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--input", default="tmp/conversation_hooks.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(args.env_file))
    supabase_url = require_env("SUPABASE_URL")
    key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for nickname, hooks in data.items():
        cleaned = [
            {"text": str(h["text"]).strip(), "basis": str(h.get("basis") or "").strip()}
            for h in hooks if str(h.get("text") or "").strip()
        ]
        too_long = [h["text"] for h in cleaned if len(h["text"]) > MAX_HOOK_CHARS]
        if too_long:
            raise SystemExit(f"{nickname}: {MAX_HOOK_CHARS}文字を超える一言があります: {too_long}")
        rows.append({"member_nickname": nickname, "hooks": cleaned, "updated_at": now})
        print(f"{nickname}: " + " / ".join(h["text"] for h in cleaned))

    if args.dry_run:
        print("--dry-run: no writes to Supabase.")
        return 0
    req = Request(
        f"{supabase_url}/rest/v1/member_conversation_hooks?on_conflict=member_nickname",
        data=json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60):
            pass
    except HTTPError as exc:
        raise SystemExit(f"Supabase upsert failed {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    print(f"upserted {len(rows)} members")
    return 0


if __name__ == "__main__":
    sys.exit(main())
