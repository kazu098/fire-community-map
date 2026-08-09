# 🗾 fire-community-map

コミュニティ会員マップ - 日本地図上に会員の居住地・旅行/グルメ情報を表示するプロジェクト

## 概要

- **会員マップ**: Googleフォームで収集した会員の居住地（都道府県〜市区町村レベル）とアバターを日本地図上にピン表示
- **旅行・グルメマップ**: Discordの旅行/グルメチャンネルへの投稿（画像・テキスト・投稿者）を日本地図上に表示。ピンをクリックすると投稿内容を確認可能
- **限定共有**: WordPress会員ページは作らず、Vercel等にデプロイした限定URLを知っている人だけが閲覧

## 技術スタック

| 用途 | 技術 |
|------|------|
| 地図表示 | [Leaflet.js](https://leafletjs.com/) (無料) |
| 地図タイル | [OpenStreetMap](https://www.openstreetmap.org/) / 国土地理院 (無料) |
| ジオコーディング | [Geolonia住所ジオコーダー](https://geolonia.com/) / 都道府県静的JSON (無料) |
| データ保存 | Supabase Postgres / Supabase Storage |
| Discord連携 | Discord Bot API (定期バッチ取得) |
| デプロイ | Vercel等のホスティング |

## 方針

- Google Maps API は**使わない**（すべて無料の範囲で実装）
- 住所はフォーム入力時点で都道府県〜市区町村レベルに限定済み（プライバシー配慮済み）
- Discord投稿はリアルタイム連携せず**定期バッチ（1日1回）**で取得し、地図はSupabaseの表示用データのみ参照
- 認証・ベーシック認証・WordPress会員制プラグインは使わず、限定URL共有を前提にする
- Supabaseには表示に必要な最小限の情報だけを保存し、本名・メールアドレス・電話番号・詳細住所は保存しない

## WordPressへのメンバー一覧埋め込み

公開メンバー一覧をWordPress内に表示する場合は、埋め込み専用入口の `public-embed.html` をiframeで読み込みます。

```html
<iframe
  id="fire-member-directory"
  src="https://fire-community-map.example.com/public-embed.html"
  style="width:100%; min-height:900px; border:0; display:block;"
  loading="lazy"
></iframe>
<script>
window.addEventListener('message', event => {
  if (event.data?.type !== 'fire-member-directory-height') return;
  const iframe = document.getElementById('fire-member-directory');
  if (iframe) iframe.style.height = `${event.data.height}px`;
});
</script>
```

`public.html?embed=1` でも同じ埋め込み表示になります。

## ディレクトリ構成（予定）

```
fire-community-map/
├── README.md
├── TODO.md
├── docs/              # 設計・仕様メモ
├── scripts/
│   ├── geocode.gs     # GAS: 住所→緯度経度変換
│   ├── export_json.gs # GAS: スプレッドシート→JSON出力
│   └── discord_batch.py  # Discord投稿取得バッチ（必要な場合）
├── index.html         # サイト本体（メンバー一覧・Leafletマップ）
├── data/              # ローカル確認用JSON/画像
├── supabase/
│   └── schema.sql     # Supabaseテーブル/RLS定義
└── api/               # Vercel API Route / Serverless Function（必要な場合）
```

## セットアップ手順

→ [TODO.md](./TODO.md) を参照

## Discordアバター突合

Googleフォーム回答のニックネームとDiscordサーバー上の表示名を完全一致で突合し、アバター候補をJSONに出力します。

```bash
python3 scripts/match_discord_avatars.py \
  --members-csv path/to/form_responses.csv \
  --output tmp/member_avatar_matches.json
```

完全一致しないが本人確認済みの表示名差分は、`config/member_discord_name_map.csv` に `form_nickname,discord_display_name` 形式で追加します。出力の `nickname` はGoogleフォーム側の値を維持し、Discord表示名はアバター照合にだけ使います。

`.env` には以下を設定します。

```env
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
GOOGLE_SHEET_ID=...
GOOGLE_SHEET_NAME=Form Responses 1
```

Google Sheetsが認証必須の場合、まず回答シートをCSVとしてエクスポートし、`--members-csv` に渡します。公開CSVとして読めるシートであれば、`--members-csv` を省略すると `GOOGLE_SHEET_ID` / `GOOGLE_SHEET_NAME` から直接読み込みます。

## 住所正規化

Googleフォームの自由入力住所を、Supabase投入用の `location_text`, `prefecture`, `municipality_optional`, `location_level`, `lat`, `lng`, `map_lat`, `map_lng` に正規化します。

```bash
python3 scripts/normalize_member_locations.py \
  --members-csv path/to/form_responses.csv \
  --output-json tmp/member_locations_normalized.json \
  --output-csv tmp/member_locations_normalized.csv
```

`lat` / `lng` は元入力を正規化した代表座標です。同じ代表座標に複数人が集まる場合は、地図表示用の `map_lat` / `map_lng` を少しずらして出力します。DBには両方保存し、地図マーカーは `map_lat` / `map_lng` を使います。

表記ゆれや地方名は `config/location_aliases.csv` で補完します。都道府県のみの入力は `config/prefecture_centroids.csv` の代表座標を使い、市区町村はGeoloniaの公開住所データから代表点を計算します。

## アバターStorage保存

Discordアバター突合結果から画像をダウンロードし、Supabase Storageの `member-avatars` bucketへ保存します。まず保存予定パスだけ確認する場合はdry-runを使います。

```bash
python3 scripts/upload_member_avatars.py \
  --matches tmp/member_avatar_matches.json \
  --output tmp/member_avatar_storage_paths.json \
  --dry-run
```

実アップロード時は `.env` に以下を設定します。

```env
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

bucket作成も含める場合:

```bash
python3 scripts/upload_member_avatars.py \
  --matches tmp/member_avatar_matches.json \
  --output tmp/member_avatar_storage_paths.json \
  --create-bucket
```

Storage pathにはDiscordユーザーIDを含めません。出力JSONの `avatar_path` を `member_locations.avatar_path` に保存します。

## Googleフォーム回答の差分同期

Googleフォーム回答シートから新しく追加されたメンバーだけをSupabaseへ追加します。まずdry-runで対象件数を確認します。

フォーム送信時点で自動同期したい場合は、GitHub Actions と Apps Script を使う [Googleフォーム送信時のメンバー自動追加](./docs/member-form-submit-automation.md) を参照してください。

```bash
python3 scripts/sync_member_location_deltas.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/1PWU_Kx-bRJphF2KONPssu5DmxhlQEXmKHCwu9DaWK00/edit?usp=sharing" \
  --dry-run
```

問題なければ `--dry-run` を外して実行します。

```bash
python3 scripts/sync_member_location_deltas.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/1PWU_Kx-bRJphF2KONPssu5DmxhlQEXmKHCwu9DaWK00/edit?usp=sharing"
```

既存メンバーの住所変更も反映したい場合だけ、`--update-existing` を付けます。通常の追加運用では付けません。

Google Sheetが公開CSVとして読めない場合は、フォーム回答をCSVでエクスポートして `--members-csv path/to/form_responses.csv` を渡します。

## Discord旅行グルメ投稿の差分同期

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

## コミュニティ投稿(読んだ本・旅行・質問相談・note・お金の相談・介護医療・子育て・不動産)の収集

対象は8チャンネル(`雑談` `質問・相談コーナー` `お金の話・相談` `こんな本読みました` `旅行` `介護・医療` `子育て` `不動産`)。詳細はGitHub issue #59を参照。収集→要約→反映の3段階で、要約はAPI課金なし(Claude Codeとの対話セッションで実施、Anthropic APIキーなどは使わない)。

対象チャンネルへの「View Channel」「Read Message History」権限をF研Botに付与してもらう必要があります(管理者に依頼)。

1. 生データの収集(要約なし):

```bash
python3 scripts/fetch_community_posts.py --since 2026-01-01T00:00:00+09:00  # 初回のみ --since が必要
python3 scripts/fetch_community_posts.py  # 2回目以降は data/community_posts_sync_state.json の続きから
```

2026年以降の全チャンネルを取り直す場合は、既存の同期状態を使わずに次を実行します。

```bash
python3 scripts/fetch_community_posts.py --reset-state --since 2026-01-01T00:00:00+09:00
```

`tmp/community_posts_raw.json` に生メッセージが書き出されます。

2. Claude Codeとの対話で `tmp/community_posts_raw.json` を確認しながら、一覧に載せる価値がある投稿を選び、タイトル・要約を付けて `tmp/community_posts_curated.json` を作成します(`load_member_profiles.py` の `MEMBER_TAGS` と同じく人手レビュー済みの確定データという位置付け)。

3. Supabaseへ反映:

```bash
python3 scripts/load_community_posts.py --dry-run
python3 scripts/load_community_posts.py
```

✕ボタンで非表示にされた投稿(`community_posts_history` に `action=delete` が記録されたもの)は自動的にスキップされ、再クロールしても復活しません。

### コミュニティ投稿候補の定期確認

`.github/workflows/sync-community-content.yml` で毎日 05:45 JST に、前回リポジトリへ反映された `data/community_posts_sync_state.json` 以降の差分だけを取得します。処理後は同期stateを自動commitするため、同じ差分を毎日繰り返しIssue化しません。

- `こんな本読みました` は、本文から本タイトルを抽出でき、投稿者が `member_profiles` に一致する場合だけ自動でSupabaseへ反映します。
- 読書投稿でも、タイトルを本文から確定できないもの、投稿者が未マッピングのもの、短文返信っぽいものはGitHub Issueに回します。
- 旅行/グルメ系は、自動投稿に寄せやすい候補としてGitHub Issueにまとめます。
- お金・介護/医療・子育て・不動産・質問相談は、内容確認が必要な「暮らしの知恵」候補としてGitHub Issueにまとめます。
- 旅行グルメで画像と場所の手がかりがある投稿は、地図追加候補として確認します。
- 候補がある場合だけ `暮らしの知恵・旅行グルメ候補の確認が必要です - YYYY-MM-DD` というGitHub Issueを作成します。同日のIssueが既に開いている場合はコメント追記します。

ローカルで同じ候補抽出だけ確認する場合:

```bash
python3 scripts/fetch_community_posts.py
python3 scripts/build_auto_book_posts.py \
  --raw tmp/community_posts_raw.json \
  --curated tmp/community_posts_curated.json \
  --output tmp/community_posts_book_auto.json \
  --review-output tmp/community_posts_book_review_needed.md \
  --count-output tmp/community_posts_book_auto_count.txt \
  --review-count-output tmp/community_posts_book_review_count.txt
python3 scripts/build_community_content_review_report.py \
  --raw tmp/community_posts_raw.json \
  --curated tmp/community_posts_book_auto.json \
  --travel-posts data/travel_posts.json \
  --output tmp/community_content_review_needed.md \
  --count-output tmp/community_content_review_count.txt
```

承認後は、暮らしの知恵と例外扱いの読書投稿は `tmp/community_posts_curated.json` を整えて `scripts/load_community_posts.py` でSupabaseへ反映し、旅行グルメは `scripts/sync_travel_posts.py` と `scripts/load_travel_posts_to_community_posts.py` で地図・メンバー詳細へ反映します。旅行グルメも自動投稿まで進める場合は、画像保存・場所推定・投稿者マッピングがすべて通った投稿だけを自動反映対象に広げます。

## Discordイベント開催記録

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

### イベント同期の定期実行

`.github/workflows/sync-community-events.yml` で毎日 05:30 JST に同期します。

- Discordの「イベント作成」機能で作られたサーバーイベントは、自動で `community_events` にupsertします。
- チャンネル投稿由来のイベント候補は自動投入せず、直近3日分から告知・募集らしい投稿だけを抽出します。
- 人手確認が必要な候補がある場合は、GitHub Issue `イベント候補の確認が必要です - YYYY-MM-DD` を作成します。

通知はGitHub Issue経由です。リポジトリをWatchしていればGitHub通知/メールで届き、Slack連携している場合はSlackにも流せます。

GitHub Actionsには以下のRepository secretsが必要です。

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## note用のF研通信下書き生成

F研通信のような月次・隔週の活動報告は、Discordから収集済みのJSONを元にMarkdown下書きを生成できます。noteへの投稿やAI API呼び出しは行わず、編集者が確認して貼り付けるための素材を作ります。本文は募集・告知ではなく、開催済みの活動記録として過去形でまとめます。

先にイベント系・投稿系のDiscord同期を実行します。

```bash
python3 scripts/fetch_community_events.py
python3 scripts/fetch_community_posts.py
```

月2回運用のnote貼り付け用下書き:

```bash
# 1日0:00〜15日12:00分。毎月15日12:00に作成する想定。
python3 scripts/generate_note_activity_draft.py \
  --month 2026-08 \
  --half first
```

```bash
# 15日12:00直後〜月末12:00分。月末12:00に作成する想定。
python3 scripts/generate_note_activity_draft.py \
  --month 2026-08 \
  --half second
```

出力先はそれぞれ以下になります。

- `tmp/note_drafts/fken-tsushin-2026-08-first-half-paste.md`
- `tmp/note_drafts/fken-tsushin-2026-08-second-half-paste.md`

月次のnote貼り付け用下書きも必要なら作成できます。

```bash
python3 scripts/generate_note_activity_draft.py \
  --month 2026-07 \
  --output tmp/note_drafts/fken-tsushin-2026-07-paste.md
```

上記は `--template editorial --delivery paste` がデフォルトです。noteに貼る最終成果物では、編集メモやDiscord参照リンクを出さないため `--include-source-links` は付けません。

月2回運用では、イベント系だけでなく `tmp/community_posts_raw.json` の旅行・本・お金の話・介護/医療なども本文候補に含めます。Discord添付画像が取れる場合だけ `画像候補:` として残します。

作成ルールは `prompts/fken_tsushin_note_draft.md` に固定しています。

直近14日分の下書き:

```bash
python3 scripts/generate_note_activity_draft.py \
  --last-days 14 \
  --output tmp/note_drafts/fken-tsushin-latest-paste.md
```

出力先はデフォルトで `tmp/note_drafts/fken-tsushin-開始日_終了日.md` です。`--output tmp/note_drafts/custom.md` で変更できます。

生成される範囲は、Discordから拾える開催済み活動、盛り上がった話題、画像候補が中心です。宣伝セクションは既存note記事の固定文をコピーして追記する想定です。

画像はDiscord添付画像のURLを「画像候補」として出します。Discord CDNのURLは期限切れになることがあるため、noteに載せる写真は下書き確認時に早めに保存・アップロードしてください。

自動実行する場合は、毎月15日12:00に `--half first`、月末12:00に同月の `--half second` を実行します。GitHub Actions化する場合も、最終的には生成されたMarkdownを投稿担当者が確認してからnoteへ貼り付けます。
