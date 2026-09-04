# Discord旅行グルメ投稿の差分同期

旅行チャンネルとグルメ・料理チャンネルの投稿を取得し、場所を推測できた画像付き投稿を `data/travel_posts.json` に追記します。グルメ・料理は外食・店・旅先グルメと判断できる投稿だけを対象にします。投稿画像と投稿者アイコンは `data/travel-photos/` / `data/travel-avatars/` に保存します。場所を推測できない投稿はスキップします。

初回だけ、読み始める日時を指定します。

```bash
python3 scripts/sync_travel_posts.py \
  --since 2026-06-28T22:00:00+09:00
```

以後は `data/travel_sync_state.json` のチャンネル別 `last_scanned_message_id` から先だけを読みます。

```bash
python3 scripts/sync_travel_posts.py --dry-run
python3 scripts/sync_travel_posts.py
```

`--dry-run` で新規件数を確認し、問題なければ `--dry-run` を外して実行します。既存の投稿は `discord_message_id` で重複排除されます。
