# 📋 TODO

## ステップ1: 静的な会員マップを作る

- [x] Googleフォームでニックネーム + 住所（都道府県〜市区町村）を収集
- [x] 回答をスプレッドシートに集約
- [x] ✅ プライバシー配慮: フォーム設計の段階で都道府県〜市区町村レベルの入力に限定済み。座標の丸め処理は不要
- [ ] 住所を緯度経度に変換（ジオコーディング）。フォーム回答はすでに **都道府県〜市区町村レベル** で収集済みのため座標の丸め不要
  - [ ] 都道府県のみの回答 → 47都道府県の代表座標を静的JSONルックアップテーブルで引く（API不要）
  - [ ] 市区町村まである回答 → **Geolonia住所ジオコーダー** に「東京都渋谷区」形式で渡して代表座標を取得
  - [ ] GASで住所列を見て都道府県のみ/市区町村ありを分岐し、上記2パターンで座標を取得するスクリプトを書く
  - [ ] 変換結果（ニックネーム・都道府県・市区町村・緯度・経度）をJSONファイルに出力する
- [ ] Discord APIで会員のアバター画像を取得し、マーカー用に自分のサーバーへ保存する
  - [ ] フォーム回答にDiscordユーザーIDを収集するカラムを追加する
  - [ ] Discord APIでユーザーIDからアバター画像URLを生成するスクリプトを書く
  - [ ] 画像を `/wp-content/uploads/member-avatars/` にダウンロード保存する
  - [ ] 取り込み日時を記録しておき、アバターURL変更時に再取得できるようにする
- [ ] スプレッドシートをJSON化し、Leafletで読み込んでマーカー表示するHTMLを作る
  - [ ] GASでスプレッドシートをJSON出力するスクリプトを書く（フィールド例: nickname, prefecture, lat, lng, avatarPath）
  - [ ] JSONをWordPressサーバーにアップロードできる形式・場所に配置する
  - [ ] Leaflet.js初期化・マーカー表示・ポップアップ（バルーン）のHTMLを実装する
  - [ ] アバター画像をマーカーアイコンとして使うカスタムアイコン設定を行う
- [ ] 動作確認（拡大縮小・バルーン表示）。スクショで共有して叩き台にする

## ステップ2: WordPressで会員限定ページにする

- [ ] 会員制プラグイン（Members / Restrict Content など）でページをログイン者限定にする
  - [ ] MembersまたはRestrict Content Proプラグインをインストール・有効化する
  - [ ] 会員マップページを「ログイン済みユーザーのみ」に制限する設定を行う
  - [ ] 非ログインユーザーがログインページへリダイレクトされることを確認する
- [ ] ステップ1のHTMLを自サーバーに置き、iframeで会員ページに埋め込む
  - [ ] LeafletマップのHTMLファイルをサーバーに配置する（例: `/map/index.html`）
  - [ ] WordPressの固定ページにiframeタグで埋め込む（src・height・widthを設定）
  - [ ] スマホ表示でも崩れないようレスポンシブ対応（width:100%, aspect-ratio等）を確認する
- [ ] （代替案）WordPressのLeaflet系プラグインのOpenStreetMapモードで表示する方法も検討

## ステップ3: Discord旅行チャンネルを連携する

- [x] Discord Developer PortalでBotを作成し、Bot Token を取得する（Bot名: F研Bot）
  - [x] applications.commands / bot スコープで招待URLを生成しサーバーに追加する
  - [x] Bot TokenをWordPressサーバーの環境変数または設定ファイルに安全に保存する
- [x] **Message Content Intent** をオン（投稿本文を読むために必須）
- [ ] サーバー管理者にBotの追加と旅行チャンネルの閲覧権限付与を依頼する
  - 依頼文: 「Botをサーバーに追加したいので、下記の招待リンクをクリックして追加をお願いできますか？あわせて旅行チャンネルをBotに見られるようにしてほしいです。」
- [ ] 定期バッチ（1日1回）で旅行/グルメチャンネルの投稿（場所・写真・一言）を取得する
  - [ ] WordPressのMySQLに `wp_travel_posts` カスタムテーブルを作成する
    - フィールド: `id, discord_user_id, nickname, avatar_local_path, prefecture, photo_local_path, comment, discord_message_id, posted_at`
  - [ ] テーブル作成SQLをファイルに保存しバージョン管理する → `wp/setup.sql`
  - [ ] Pythonで Discord APIからチャンネル投稿を取得するスクリプトを書く → `scripts/discord_batch.py`
  - [ ] 添付画像を `/wp-content/uploads/travel-photos/YYYY-MM/` にダウンロード保存する
  - [ ] `discord_message_id` で重複チェックし、未取り込みの投稿だけDBに保存する
  - [ ] サーバーのcron（またはWP-Cron）でスクリプトを1日1回自動実行する設定をする
- [ ] AIで都道府県を判定し、写真・コメントと一緒にJSON/DBへ保存する
  - [ ] まずキーワードマッチ（都道府県名・地名辞書）で判定するルールベースロジックを実装する
  - [ ] 判定できなかった投稿はprefectureをNULLで保存し、地図には表示しない運用にする
  - [ ] 精度を上げたい場合はOpenAI APIなど外部LLMへの問い合わせを追加する（コスト要確認）
- [ ] 地図はそのJSON/DBだけを読むようにする（表示時にDiscordへアクセスしない＝負荷ゼロ）
  - [ ] バッチ末尾に `wp_travel_posts` からLeaflet用JSONを生成・上書き保存するステップを追加する
  - [ ] LeafletのHTMLはそのJSONファイルのみ読み込むよう実装し、Discord APIへの直接アクセスがないことを確認する
- [ ] 会員は今まで通りDiscordに投稿するだけでよい（新しいフォームは作らない）

## コスト・注意点

- [ ] Leaflet.js・OpenStreetMap・Geolonia/国土地理院APIの利用規約とクレジット表記要件を確認する
- [ ] WordPressプラグイン（Members等）の無料プランで会員制限機能が要件を満たすか確認する
- [x] ✅ 住所のプライバシー配慮: フォーム入力時点で対応済み
- [ ] DiscordのアバターURLは変わることがあるので、取り込み時に自サーバーへ保存しておく
- [ ] Bot方式はDiscord公式の正規ルート（規約面で安心）
