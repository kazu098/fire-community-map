# 週次ダイジェスト(weekly digest)

忙しくてDiscordを追いきれないメンバー向けに、直近1週間の動きをふぁいにゃが「今日の振り返り」チャンネルに要約投稿する機能。[F研通信](./note-activity-draft.md)(月2回・編集者がレビューして note に貼る長文記事)とは別物で、こちらは編集を挟まずbotが自動投稿する短いDiscordメッセージ。

## バッチ(`scripts/generate_weekly_digest.py`)

`scripts/generate_note_activity_draft.py` の活動収集ロジック(`collect_events`)を再利用しつつ、投稿の選定は独自に行う。ノート記事のような段落構成の文章は作らず、直近7日分(`--days`)から「盛り上がった話題(タイトル：一言要約＋Discordパーマリンク)」を最大`--max-highlights`件(デフォルト4)だけ箇条書きにする軽量な要約。

- リアルなオフ会・イベント(`collect_events`が拾ったもの)を優先し、残り枠を**リアクション数が多い投稿**(`select_top_posts`)で埋める。リアクション数はDiscordのメッセージ取得時に既に付与されている`reactions`配列を集計したもの(`scripts/fetch_community_posts.py`の`reaction_count`フィールド)で、投稿収集のための追加API呼び出しは不要
- リアクションが誰も付いていない投稿同士は、投稿の文字数(充実度)をタイブレークにする
- 要約は文字数で単純に切らず、文末(。！？)で切る(`trim_to_sentence`)。「...ITチーム以外の人も興味があれば参...」のような文の途中で切れた要約にならないようにしている
- `--days`: 集計対象の遡り日数(デフォルト7)
- `--events-raw`/`--events-curated`/`--posts-raw`: `scripts/fetch_community_events.py`/`scripts/fetch_community_posts.py` が出力するJSON
- `--max-highlights`: ダイジェスト本文に含める箇条書きの最大件数(デフォルト4)
- `--post-to-discord`: `DISCORD_DIGEST_CHANNEL_ID`/`DISCORD_BOT_TOKEN` が未設定ならDiscord投稿だけスキップ(標準出力には内容が出る)

### 収集対象チャンネル

`scripts/fetch_community_posts.py --include-digest-channels` を付けて実行すると、note下書き用の8チャンネル(`CHANNEL_CONTENT_TYPES`)に加えて`DIGEST_EXTRA_CHANNEL_NAMES`の15チャンネル(noteの話、株式投資、代替資産、私のポートフォリオ、今日の運動、ゲーム、麻雀部、ハイキング倶楽部、バケットリスト、グルメ・料理、ガーデニング・畑、aiの話、ペット・動物、短歌・川柳、ダイエット)もスキャンする。追加分は`content_type=other`でタグ付けされ、F研通信のカテゴリ別レンダリング(`render_topic_section`)には影響しない(`--include-digest-channels`を付けない限りF研通信の生成では一切スキャンされない)。

対象は「チャット」「お金」「暮らし」「イベント」カテゴリの**公開**チャンネルのみ。以下は意図的に除外している。

- `[非公開]`/`[プライベート]`カテゴリ(discord作業用メモ、hsp・内向型、fire済み向け生活相談、未fire向け仕事相談、メンタルダウンの話など): アクセスが限定されたチャンネルの内容を、より広い読者が見るチャンネルへ要約して再投稿すべきではないため
- `FIRE研究所アカウント関連`カテゴリ(各運営チームの作業チャンネル)、`初めての方`カテゴリ: メンバー向けの話題ではなく運営・オンボーディング用のため
- 宣伝、運営からのお知らせ、重要なお知らせ: 会話ではなく告知のためのチャンネルなので「盛り上がった話題」の対象にならない
- 今日の振り返り、ゆるマッチング: ふぁいにゃ自身がbotとして投稿している先そのものなので、自分の投稿を拾って無限ループ的にダイジェストしないよう除外

イベント収集(`fetch_community_events.py`)側のチャンネル範囲は変更していない(既存のF研通信向けイベント収集をそのまま流用)。

投稿先は「今日の振り返り」チャンネル(channel_id: `1389922995266523166`)。[ゆるマッチング](./yuru-matching.md)と同様、新しいチャンネルは作らず既存のふぁいにゃ発信の場に相乗りする方針。

## ワークフロー(`.github/workflows/post-weekly-digest.yml`)

毎週月曜 06:00 JST に、`fetch_community_events.py`/`fetch_community_posts.py` で直近8日分(バッファ込み)を取得し直してから `generate_weekly_digest.py --post-to-discord` を実行する。[generate-note-draft.yml](../.github/workflows/generate-note-draft.yml) と同じく `--reset-state`+`tmp/`配下の一時state fileを使い、本番の同期state(`data/community_*_sync_state.json`)には触れない。

## 文体

ふぁいにゃの一人称ルールは[docs/fainya-persona.md](./fainya-persona.md)に従う。ダイジェストは「にゃ」を要所要所(書き出しと締め程度)に使う軽いトーンで、[ゆるマッチング](./yuru-matching.md)のアナウンス文と同じ調整(全文にゃにゃしない)。
