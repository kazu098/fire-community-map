# 🗾 fire-community-map

コミュニティ会員マップ - 日本地図上に会員の居住地・旅行/グルメ情報を表示するプロジェクト

## 概要

- **会員マップ**: Googleフォームで収集した会員の居住地（都道府県〜市区町村レベル）とアバターを日本地図上にピン表示
- **旅行・グルメマップ**: Discordの旅行/グルメチャンネルへの投稿（画像・テキスト・投稿者）を日本地図上に表示。ピンをクリックすると投稿内容を確認可能
- **会員限定**: WordPressのログイン者のみ閲覧可能

## 技術スタック

| 用途 | 技術 |
|------|------|
| 地図表示 | [Leaflet.js](https://leafletjs.com/) (無料) |
| 地図タイル | [OpenStreetMap](https://www.openstreetmap.org/) / 国土地理院 (無料) |
| ジオコーディング | [Geolonia住所ジオコーダー](https://geolonia.com/) / 都道府県静的JSON (無料) |
| データ保存 | WordPress MySQL カスタムテーブル (`wp_travel_posts`) |
| Discord連携 | Discord Bot API (定期バッチ取得) |
| 会員制限 | WordPress プラグイン (Members / Restrict Content) |

## 方針

- Google Maps API は**使わない**（すべて無料の範囲で実装）
- 住所はフォーム入力時点で都道府県〜市区町村レベルに限定済み（プライバシー配慮済み）
- Discord投稿はリアルタイム連携せず**定期バッチ（1日1回）**で取得し、地図はJSONファイルのみ参照

## ディレクトリ構成（予定）

```
fire-community-map/
├── README.md
├── TODO.md
├── docs/              # 設計・仕様メモ
├── scripts/
│   ├── geocode.gs     # GAS: 住所→緯度経度変換
│   ├── export_json.gs # GAS: スプレッドシート→JSON出力
│   └── discord_batch.py  # Discord投稿取得バッチ
├── map/
│   ├── index.html     # Leafletマップ本体
│   └── data/          # 地図用JSONファイル置き場
└── wp/
    └── setup.sql      # wp_travel_postsテーブル作成SQL
```

## セットアップ手順

→ [TODO.md](./TODO.md) を参照
