# Discordイベント開催記録

イベントは「暮らしの知恵」とは別のタブで表示します。Discordの告知・振り返り投稿をそのまま一覧化するのではなく、開催単位で人手レビュー済みの `tmp/community_events_curated.json` を作成し、Supabaseの `community_events` へ反映します。

初回は `supabase/community_events.sql` をSupabaseに適用してください。

Discordからの取得は、イベント系チャンネルの投稿と、Discordの「イベント作成」機能で作られたサーバーイベントの両方を対象にします。

```bash
python3 scripts/fetch_community_events.py --since 2026-01-01T00:00:00+09:00
python3 scripts/fetch_community_events.py
```

`tmp/community_events_raw.json` に raw 候補が書き出されます。サーバーイベント由来の行は `source_type: "scheduled_event"` として入り、`discord_permalink` は `https://discord.com/events/...` になります。

`tmp/community_events_curated.json` の例:

```json
[
  {
    "title": "オンライン雑談会",
    "tags": ["交流会", "雑談"],
    "starts_at": "2026-08-10T20:00:00+09:00",
    "ends_at": "2026-08-10T21:30:00+09:00",
    "format": "online",
    "prefecture": "オンライン",
    "location_label": "Discordボイス",
    "participant_count": 12,
    "participation_note": "告知投稿にリアクション",
    "summary": "新メンバー同士の交流を目的に開催。",
    "highlights": "初参加者も話しやすい雰囲気だった。",
    "learnings": "冒頭に自己紹介タイムを固定で入れるとよさそう。",
    "discord_channel_name": "イベント告知",
    "discord_message_id": "123456789012345678",
    "discord_permalink": "https://discord.com/channels/..."
  }
]
```

反映:

```bash
python3 scripts/load_community_events.py --dry-run
python3 scripts/load_community_events.py
```

画面では `starts_at` / `ends_at` を見て「これから開催」「開催済み」に自動で分けます。イベント種別はタブではなく、カード内の小さなタグとして表示します。

## イベント同期の定期実行

`.github/workflows/sync-community-events.yml` で毎日 05:30 JST に同期します。

- Discordの「イベント作成」機能で作られたサーバーイベントは、自動で `community_events` にupsertします。
- Discordの予定一覧から消えたサーバーイベントは、開催済みとして画面に残すため自動削除しません。削除したい場合だけ `scripts/sync_scheduled_events.py --delete-stale` を使います。
- チャンネル投稿由来のイベント候補は自動投入せず、直近3日分から告知・募集らしい投稿だけを抽出します。
- 人手確認が必要な候補がある場合は、GitHub Issue `イベント候補の確認が必要です - YYYY-MM-DD` を作成します。

通知はGitHub Issue経由です。リポジトリをWatchしていればGitHub通知/メールで届き、Slack連携している場合はSlackにも流せます。

GitHub Actionsには以下のRepository secretsが必要です。

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
