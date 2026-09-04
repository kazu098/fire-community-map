# 週次ダイジェスト(weekly digest)

忙しくてDiscordを追いきれないメンバー向けに、直近1週間の動きをふぁいにゃが「今日の振り返り」チャンネルに要約投稿する機能。[F研通信](./note-activity-draft.md)(月2回・編集者がレビューして note に貼る長文記事)とは別物で、こちらは編集を挟まずbotが自動投稿する短いDiscordメッセージ。

## バッチ(`scripts/generate_weekly_digest.py`)

`scripts/generate_note_activity_draft.py` の活動収集ロジック(`collect_events`/`collect_post_topics`)をそのまま再利用し、直近7日分(`--days`)のイベントとチャンネル別投稿を箇条書きに要約する。ノート記事のような段落構成の文章は作らず、「タイトル：一言要約」「カテゴリ：件数(例の投稿)」を並べるだけの軽量な集計。

- `--days`: 集計対象の遡り日数(デフォルト7)
- `--events-raw`/`--events-curated`/`--posts-raw`: `scripts/fetch_community_events.py`/`scripts/fetch_community_posts.py` が出力するJSON
- `--max-lines`: ダイジェスト本文に含める箇条書きの最大件数(デフォルト8。全部載せず「気になったら覗いてね」で締める設計)
- `--post-to-discord`: `DISCORD_DIGEST_CHANNEL_ID`/`DISCORD_BOT_TOKEN` が未設定ならDiscord投稿だけスキップ(標準出力には内容が出る)

投稿先は「今日の振り返り」チャンネル(channel_id: `1389922995266523166`)。[ゆるマッチング](./yuru-matching.md)と同様、新しいチャンネルは作らず既存のふぁいにゃ発信の場に相乗りする方針。

## ワークフロー(`.github/workflows/post-weekly-digest.yml`)

毎週月曜 06:00 JST に、`fetch_community_events.py`/`fetch_community_posts.py` で直近8日分(バッファ込み)を取得し直してから `generate_weekly_digest.py --post-to-discord` を実行する。[generate-note-draft.yml](../.github/workflows/generate-note-draft.yml) と同じく `--reset-state`+`tmp/`配下の一時state fileを使い、本番の同期state(`data/community_*_sync_state.json`)には触れない。

## 文体

ふぁいにゃの一人称ルールは[docs/fainya-persona.md](./fainya-persona.md)に従う。ダイジェストは「にゃ」を要所要所(書き出しと締め程度)に使う軽いトーンで、[ゆるマッチング](./yuru-matching.md)のアナウンス文と同じ調整(全文にゃにゃしない)。
