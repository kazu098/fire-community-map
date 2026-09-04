# 技術スタック・方針・ディレクトリ構成

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
├── index.html         # サイト本体（メンバー一覧・Leafletマップ）
├── data/              # ローカル確認用JSON/画像
├── supabase/
│   └── schema.sql     # Supabaseテーブル/RLS定義
└── api/               # Vercel API Route / Serverless Function（必要な場合）
```
