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
├── map/
│   ├── index.html     # Leafletマップ本体
│   └── data/          # ローカル確認用JSON/画像
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
