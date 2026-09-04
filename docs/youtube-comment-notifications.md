# YouTubeコメント通知

YouTubeチャンネルの公開コメントを定期チェックし、新着コメントだけDiscordへ通知します。GitHub Actionsの `Notify YouTube comments` workflow が1時間に1回 `scripts/notify_youtube_comments.py` を実行します。

初回実行では既存コメントを通知せず、現在見えているコメントIDだけを `data/youtube_comment_notify_state.json` に記録します。2回目以降に新しく見つかったコメントだけDiscordへ投稿します。

サーバー内チャンネルに通知する場合は、GitHub Secretsに以下を設定します。

```env
YOUTUBE_API_KEY=...
YOUTUBE_CHANNEL_ID=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=1543164715998519366
DISCORD_NOTIFY_USER_ID=1478666928083173436
```

Webhookを使う場合は、`DISCORD_CHANNEL_ID` の代わりに `DISCORD_WEBHOOK_URL` を設定しても動きます。

Discordの個人DMに通知する場合は、既存の `DISCORD_BOT_TOKEN` に加えて以下を設定します。

```env
DISCORD_DM_USER_ID=1478666928083173436
```

公開コメントの取得だけならYouTubeログイン情報は不要です。保留中コメントや非公開情報まで扱う場合は、チャンネル所有者のOAuth認可が別途必要です。
