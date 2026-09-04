# 🗾 fire-community-map

FIRE研究所コミュニティの運営を支える静的サイト＋自動化スクリプト集。会員マップとして始まったが、現在は会員データ管理・コミュニティ投稿収集・イベント記録・note下書き生成・YouTubeショート動画の自動投稿まで含む、コミュニティ運営全般の裏側を担っている。

サイト本体(`index.html` / `public.html`等)はビルド不要の静的HTML。データ更新・自動化はすべて`scripts/`配下のPythonスクリプトとGitHub Actionsが担う。

## 掲載されているもの

- **会員マップ** (`index.html`): Googleフォームで収集した会員の居住地とアバターを日本地図上にピン表示
- **旅行・グルメマップ**: Discordの旅行/グルメチャンネルへの投稿を日本地図上に表示。ピンをクリックすると投稿内容を確認可能
- **公開メンバー一覧** (`public.html`): WordPress埋め込み想定の限定共有ページ → [docs/wordpress-embed.md](./docs/wordpress-embed.md)
- **コミュニティ投稿一覧**: 読んだ本・旅行・お金の相談・介護医療・子育て・不動産などのDiscord投稿を収集・整理 → [docs/community-content.md](./docs/community-content.md)
- **イベント記録**: Discordのイベント告知・サーバーイベントを開催記録として蓄積 → [docs/community-events.md](./docs/community-events.md)
- **本棚**: FIRE研究所公式本とメンバーが出版した本を本棚レイアウトで表示 → [docs/bookshelf.md](./docs/bookshelf.md)

いずれも限定URLを知っている人だけが閲覧する前提で、ログイン機能やWordPress会員制プラグインは使わない。

## ローカルでの確認方法

サイト本体はビルド不要の静的HTMLなので、ローカルで簡易サーバーを立てて開くだけで確認できる。

```bash
python3 -m http.server 8000
```

- 会員マップ: http://localhost:8000/index.html
- 公開用一覧(埋め込み想定): http://localhost:8000/public.html
- WordPress埋め込みプレビュー: http://localhost:8000/embed-preview.html

Supabaseの接続情報(URL・anon key)は`index.html`/`public.html`に直書きされている(anon keyは公開前提でRLSにより保護されているため問題ない)。ローカル確認時に`.env`は不要。

本番のBasic認証(`middleware.js`)はVercelのEdge Middlewareとしてのみ動作するため、ローカルの簡易サーバーでは認証なしで確認できる。

## 本番ビルド・デプロイ

ビルドステップは存在しない(静的HTML + Vercel Edge Middlewareのみ)。デプロイはVercelとのGit連携により、`main`ブランチへのpush/マージで自動的に本番反映される。手動でのビルドコマンドやデプロイコマンドの実行は不要。

- 変更を試したい場合は、featureブランチでPRを作成するとVercelがプレビューデプロイを自動作成する
- 本番URLへの反映は、そのPRを`main`にマージしたタイミング

## 環境変数の設定

`scripts/`配下のPythonスクリプトを実行するには、リポジトリ直下に`.env`が必要。テンプレートは[.env.example](./.env.example)を参照。

```bash
cp .env.example .env
```

`.env`はgitignore対象で、実際の値はコミットしない。値はプロジェクトオーナー(kazu098)から共有してもらう(Discord Bot Token、Supabase Service Role Keyなど機密情報を含むため、Slack/1Password等の安全な経路で受け取ること)。

Vercel本番環境には、`.env`とは別に以下の環境変数をVercelプロジェクト設定(Environment Variables)側で設定する。

- `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` — サイト全体のBasic認証(`middleware.js`が参照)

GitHub Actionsで動く定期バッチ(コミュニティ投稿同期・イベント同期・YouTubeコメント通知など)は、リポジトリのRepository secretsに個別の環境変数を設定する。必要な変数は各ドキュメント、または各workflowファイル(`.github/workflows/`)を参照。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [TODO.md](./TODO.md) | セットアップ手順 |
| [docs/tech-stack-and-policy.md](./docs/tech-stack-and-policy.md) | 技術スタック・実装方針・ディレクトリ構成 |
| [docs/member-data-pipeline.md](./docs/member-data-pipeline.md) | Discordアバター突合・住所正規化・アバターStorage保存・Googleフォーム差分同期 |
| [docs/member-form-submit-automation.md](./docs/member-form-submit-automation.md) | Googleフォーム送信時のメンバー自動追加 |
| [docs/travel-gourmet-map.md](./docs/travel-gourmet-map.md) | Discord旅行グルメ投稿の差分同期 |
| [docs/community-content.md](./docs/community-content.md) | コミュニティ投稿の収集・定期確認 |
| [docs/community-events.md](./docs/community-events.md) | Discordイベント開催記録・定期同期 |
| [docs/note-activity-draft.md](./docs/note-activity-draft.md) | note用のF研通信下書き生成 |
| [docs/youtube-comment-notifications.md](./docs/youtube-comment-notifications.md) | YouTubeコメント通知(Discordへ) |
| [docs/fire-lab-shorts-strategy.md](./docs/fire-lab-shorts-strategy.md) | YouTubeショート動画の切り抜き〜予約投稿自動化 |
| [docs/wordpress-embed.md](./docs/wordpress-embed.md) | WordPressへのメンバー一覧埋め込み |
| [docs/bookshelf.md](./docs/bookshelf.md) | 本棚タブ(F研公式本・メンバー著書)のデータ管理 |
