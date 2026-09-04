# Fire研究所 YouTube切り抜きショート動画 自動化方針

## 目的

Fire研究所の既存YouTube動画から、ショート動画向きの切り抜き候補をAIで抽出し、字幕付きの縦動画として効率よく制作する。

最初から完全自動化を狙うのではなく、まずは「AIが候補を出す」「人間が採用可否を判断する」「採用分を自動でレンダリングする」という半自動ワークフローを目指す。

## 基本方針

初期フェーズでは、以下の流れを推奨する。

1. 長尺動画を取得する
2. 音声を抽出する
3. 音声を文字起こしする
4. AIで切り抜き候補を抽出する
5. 人間が候補をレビューする
6. 採用候補を縦動画化する
7. キャプションを焼き込む
8. タイトル、概要欄、ハッシュタグ案を生成する
9. YouTube Studioから手動投稿する

投稿までの完全自動化は後回しにする。YouTube Data API経由の投稿は可能だが、OAuth、API審査、公開設定、運用ミスのリスクがあるため、初期段階では動画書き出しまでを自動化対象にする。

## ショート動画の前提

YouTube Shortsは、正方形または縦長の動画で最大3分まで対応している。

ただし、初期運用では60秒以内を基本にする。理由は以下。

- 視聴維持率を取りやすい
- 編集レビューが軽い
- 著作権音源が絡む場合のリスクを抑えやすい
- TikTok、Instagram Reelsにも転用しやすい

標準フォーマットは以下。

- 解像度: 1080x1920
- アスペクト比: 9:16
- 長さ: 15秒から60秒
- 字幕: 大きめ、2行以内、重要語を強調
- 冒頭: 1秒から2秒以内にフックを置く

## 技術スタック候補

### SaaSを使う場合

短期で検証するなら、OpusClip、Vizard、KlapなどのAI切り抜きSaaSを使う。

メリット:

- すぐ試せる
- 自動字幕、縦動画化、候補抽出が一体化している
- 非エンジニアでも運用しやすい

デメリット:

- 日本語の細かいニュアンス判定に限界がある
- 字幕やブランド表現の制御に限界がある
- 継続利用コストがかかる
- 元動画や音声を外部サービスにアップロードする必要がある

### 内製する場合

中長期では、以下の構成が現実的。

| 用途 | 候補 |
| --- | --- |
| 動画取得 | yt-dlp |
| 音声抽出 | FFmpeg |
| 文字起こし | faster-whisper, WhisperX |
| 単語単位タイムスタンプ | WhisperX |
| 話者分離 | pyannote |
| 候補抽出 | GPT, Claude, Gemini, ローカルLLM |
| 動画切り出し | FFmpeg |
| 字幕生成 | ASS字幕, SRT, FFmpeg drawtext |
| メタデータ生成 | LLM |
| 投稿 | YouTube Data API |

最初の内製版では、`yt-dlp`、`ffmpeg`、`faster-whisper`または`WhisperX`、LLM APIの組み合わせで十分。

## 切り抜き候補の評価基準

AIには、単に盛り上がっている箇所を探させるのではなく、Fire研究所の文脈に合う評価軸を渡す。

優先度が高い候補:

- 結論が明確な箇所
- 数字が含まれる箇所
- 初心者の疑問に答えている箇所
- 意外性がある箇所
- 失敗談や実体験が含まれる箇所
- 強い一言で始まる箇所
- FIRE、資産形成、新NISA、節約、副業、生活費、地方移住などのテーマが含まれる箇所

避ける候補:

- 前後文脈がないと意味が通らない箇所
- 専門用語だけで完結している箇所
- 結論までが長い箇所
- 内輪向けすぎる箇所
- 事実確認が必要な投資助言に見える箇所

## Fire研究所向けの企画パターン

Fire研究所では、以下の切り口がショート動画化しやすい。

- FIRE達成者の失敗談
- 新NISAで初心者が迷いやすいこと
- 月いくらあればFIREできるか
- サイドFIREの現実
- 会社員のまま資産形成する方法
- 節約より重要なこと
- 支出管理の考え方
- 投資でやらないほうがよいこと
- FIRE後の生活のリアル
- 地方移住と生活コスト

動画1本から、以下の3種類を作ると検証しやすい。

- 15秒から30秒: 強い一言、名言、問題提起
- 45秒から60秒: 1テーマ完結の学び
- 90秒から180秒: 深めの解説。初期は少なめにする

## 推奨ワークフロー

### フェーズ1: 半自動検証

目的は、伸びやすい切り抜きパターンを見つけること。

実装範囲:

- YouTube URLを入力する
- 動画または音声を取得する
- 文字起こしを生成する
- LLMで候補を10件程度出す
- 候補をCSVまたはMarkdownに保存する

出力例:

| 項目 | 内容 |
| --- | --- |
| start | 開始秒 |
| end | 終了秒 |
| hook | 冒頭テロップ案 |
| reason | 候補にした理由 |
| score | バズりそう度 |
| title | タイトル案 |
| caution | 注意点 |

### フェーズ2: 自動レンダリング

採用した候補から、字幕付き縦動画を自動生成する。

実装範囲:

- CSVで採用フラグを付ける
- FFmpegで該当区間を切り出す
- 1080x1920に変換する
- 字幕を焼き込む
- 書き出しファイル名を管理する

### フェーズ3: 投稿補助

投稿作業を軽くする。

実装範囲:

- タイトル案を複数生成する
- 概要欄を生成する
- ハッシュタグを生成する
- 元動画URLを概要欄に入れる
- サムネイルまたは冒頭フレームを生成する

### フェーズ4: 分析と改善

投稿後のデータをもとに、候補抽出のプロンプトを改善する。

見る指標:

- 初動再生数
- 平均視聴維持率
- 冒頭離脱率
- いいね率
- コメント率
- チャンネル登録への寄与

## フォルダ管理方針

FireCommunityMapとは別プロジェクトとして管理する。

推奨配置:

```text
/Users/ky/dev/fire-community-map/
/Users/ky/dev/fire-lab-shorts/
```

理由:

- FireCommunityMapは地図、コミュニティデータ、公開プロフィール管理のプロジェクト
- ショート動画制作は動画処理、字幕生成、投稿補助が中心
- 依存関係、データ容量、運用フローが大きく異なる
- 元動画や生成動画をGit管理に入れるべきではない

`fire-lab-shorts` は以下のように分ける。

```text
fire-lab-shorts/
  README.md
  .gitignore
  config/
    channels.yaml
    settings.yaml
  prompts/
    clip_selector.md
    title_generator.md
    caption_style.md
  data/
    videos.csv
    clips.csv
  inputs/
    raw/
    audio/
  transcripts/
    json/
    srt/
  candidates/
    clip_candidates.json
    review_queue.csv
  outputs/
    drafts/
    approved/
    uploaded/
  assets/
    fonts/
    brand/
    bgm/
  scripts/
    download.py
    extract_audio.py
    transcribe.py
    find_clips.py
    render_short.py
    generate_metadata.py
  logs/
```

Gitで管理するもの:

- `README.md`
- `.gitignore`
- `config/`
- `prompts/`
- `scripts/`
- `data/*.csv`
- `candidates/*.csv`

Gitで管理しないもの:

- 元動画
- 抽出音声
- 完成動画
- 一時ファイル
- APIキー
- OAuth認証ファイル

`.gitignore` の例:

```gitignore
inputs/
outputs/
transcripts/
logs/
.env
client_secrets.json
token.json
*.mp4
*.mov
*.wav
*.mp3
```

## 最初に作るべき最小実装

最初のゴールは、動画を書き出すことではなく、候補抽出の精度を確認すること。

最小実装:

```text
YouTube URL
  -> yt-dlpで音声取得
  -> Whisper系で文字起こし
  -> LLMで切り抜き候補抽出
  -> review_queue.csvに出力
```

この段階で、候補の質を人間が確認する。

問題なければ次に進む。

```text
review_queue.csvでapproved=true
  -> FFmpegで切り出し
  -> 字幕生成
  -> 1080x1920で書き出し
```

## このブランチでの暫定実装

本来は`fire-lab-shorts`を別フォルダまたは別リポジトリに分けるのが望ましい。ただし検証を早く回すため、このブランチではFireCommunityMap本体と独立した補助ファイルとして以下を追加した。

```text
scripts/fire_lab_shorts.py
prompts/fire-lab-shorts-candidate-selection.md
examples/fire-lab-shorts/0iL8dh6PdUI.clips.json
```

役割:

- `scripts/fire_lab_shorts.py`: YouTube素材取得、字幕TSV化、JSONマニフェストから複数ショートの一括レンダリング
- `prompts/fire-lab-shorts-candidate-selection.md`: 文字起こしから3〜5本の切り抜き候補JSONを作るためのLLMプロンプト
- `examples/fire-lab-shorts/0iL8dh6PdUI.clips.json`: 今回の動画で作った3パターンのサンプル

使い方:

```bash
# 動画と日本語自動字幕を取得
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step download

# 取得したjson3字幕をLLMに渡しやすいTSVへ変換
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step transcript

# JSON内のclipsをまとめて縦動画化
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step render

# 取得からレンダリングまで一括実行
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step all
```

出力先:

```text
/private/tmp/fire-lab-shorts/{video_id}/source.mp4
/private/tmp/fire-lab-shorts/{video_id}/transcript.tsv
/private/tmp/fire-lab-shorts/{video_id}/outputs/{clip_slug}.mp4
/private/tmp/fire-lab-shorts/{video_id}/outputs/subtitles/{clip_slug}.ass
```

新しい動画で回す場合:

1. `examples/fire-lab-shorts/{video_id}.clips.json`を作る
2. `--step download`で動画と自動字幕を取得する
3. `--step transcript`でTSVを作る
4. TSVを`prompts/fire-lab-shorts-candidate-selection.md`と一緒にLLMへ渡す
5. 返ってきたJSONを人間が確認し、誤字と切れ目を直す
6. `--step render`で3〜5本を一括生成する

注意:

- レンダリングはJSONを正として行うため、字幕の日本語品質はJSON側で担保する
- YouTube自動字幕は誤変換が多いので、公開前に必ず音声確認する
- `yt-dlp`と`ffmpeg`がローカルに必要

### 単語単位同期字幕(whisper caption source)

YouTube自動字幕(json3)はイベント単位のタイムスタンプしか持たず、字幕の切り替わりが発話とずれやすい。検証の結果、クリップの音声区間だけを切り出してfaster-whisperで単語単位のタイムスタンプを取り、それを句読点とポーズでイベント化して字幕を組み立てる方が同期精度が高いことを確認した。この方式を`--step transcribe-whisper`としてスクリプトに正式に組み込んだ。

使い方:

```bash
# faster-whisperをインストールした専用venvを用意する(例)
python3 -m venv /private/tmp/fire-lab-shorts-venv
/private/tmp/fire-lab-shorts-venv/bin/pip install faster-whisper

# マニフェストの対象クリップに "caption_source": "whisper" を設定してから
/private/tmp/fire-lab-shorts-venv/bin/python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step transcribe-whisper

# 生成された字幕ドラフトを人間が確認・修正する
#   /private/tmp/fire-lab-shorts/{video_id}/captions/{clip_slug}.json

# 確認後、通常どおりrender/validateを実行する
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step validate
python3 scripts/fire_lab_shorts.py examples/fire-lab-shorts/0iL8dh6PdUI.clips.json --step render
```

処理の流れ:

1. クリップの各`segments`区間をffmpegで音声(16kHz mono wav)として切り出す(`{video_id}/whisper/{slug}_seg{N}.wav`)
2. faster-whisperで単語単位のタイムスタンプ付き文字起こしを行う(`{video_id}/whisper/{slug}_seg{N}.words.json`にキャッシュ)
3. 単語列を句読点(。、！？)とポーズ(既定0.6秒以上の無音)でイベントにグルーピングする
4. `caption_corrections`(マニフェスト/クリップ両方)を適用する
5. 複数区間をつなげる場合はオフセットを積算して字幕ドラフトを書き出す(`{video_id}/captions/{slug}.json`)

注意:

- ドラフトは一度生成されると`--force`を付けない限り再生成されない。誤変換の手直しはこのJSONファイルを直接編集する
- `render`/`validate`は`captions/{slug}.json`が存在することを前提にする。無ければ先に`--step transcribe-whisper`を実行するよう促すエラーになる
- 既定モデルは`large-v3`。速度優先で試すときは`--whisper-model small`などに切り替えられるが、句読点の再現精度が落ちるため最終出力には向かない
- `faster-whisper`は本体プロジェクトのPython依存関係に含めていない。検証用に別venv(`/private/tmp/fire-lab-shorts-venv`など、Gitに含めない場所)を作って使う

## YouTubeへの予約投稿(アップロード自動化)

方針の当初案(投稿までの完全自動化は後回し)から一歩進めて、レンダリング済みの動画をYouTube Data API経由で予約投稿するところまで自動化した。

### 使うスクリプト

- `scripts/youtube_oauth_setup.py` — 初回だけ実行するOAuth認証。ブラウザでチャンネル所有者アカウントにログインし、`data/.youtube_oauth_token.json`(gitignore対象)にリフレッシュトークンを保存する
- `scripts/upload_youtube_short.py` — 動画ファイル・タイトル・概要欄・タグ・予約公開日時(`--publish-at`)を渡してアップロードする。`--publish-at`を指定すると非公開でアップロードされ、指定時刻にYouTube側が自動公開する
- `scripts/update_youtube_video_title.py` — アップロード後にタイトル(や概要欄・タグ)を修正する。ショート動画は確実性のため、タイトル末尾に`#Shorts`を入れる運用にした

### 事前準備(初回のみ、人間が行う)

1. Google Cloud Consoleでプロジェクトを用意し、YouTube Data API v3を有効化する
2. OAuth同意画面でテストユーザーにチャンネル所有アカウントのメールアドレスを追加する
3. 認証情報 → OAuthクライアントID → アプリケーションの種類「デスクトップアプリ」で作成し、JSONをダウンロード
4. そのJSONを`data/.youtube_oauth_client.json`として保存する(gitignore対象、コミットされない)
5. `python3 scripts/youtube_oauth_setup.py`を実行し、ブラウザでログイン・許可する

Fire研究所チャンネルでは`firelab`(プロジェクトID: `snapmeal-496901`)のOAuthクライアントを使っている。プロジェクトの表示名(Cloud Console上の名前)とOAuth同意画面のアプリ名は別々に設定できるため、認証時にGoogleの同意画面に表示されるアプリ名が想定と違っても、プロジェクトが正しければ問題ない。

### 毎回のアップロード手順

```bash
python3 scripts/upload_youtube_short.py \
  --file /path/to/short.mp4 \
  --title "タイトル #Shorts" \
  --description-file /path/to/description.txt \
  --tags FIRE 早期リタイア 資産形成 セミリタイア \
  --publish-at "2026-09-04T19:00:00+09:00"
```

`--dry-run`を付けると実際にアップロードせず内容だけ確認できる。動画ファイルはGit管理下に置かず、作業ディレクトリ(例: `/private/tmp/fire-lab-shorts/{video_id}/outputs/`)から直接参照する。

### アカウント・認証まわりの運用上の注意

- **リフレッシュトークンが7日で失効する可能性がある**: OAuth同意画面が「テスト」ステータスのままだと、Googleの仕様でリフレッシュトークンの有効期限が7日に制限される。1週間以上間隔が空くと次回アップロード時に認証エラーになるので、その場合は`scripts/youtube_oauth_setup.py`を再実行してブラウザ許可をやり直す
  - アプリを「公開」ステータスにすればこの制限は外れるが、`youtube`スコープは制限付きスコープでGoogleの審査が必要になり、個人チャンネル運用では過剰な手間になるため非推奨。頻度が週1〜月1程度なら都度再認証で十分
- **APIクォータ**: 1日10,000ユニットが上限で、動画アップロード1本につき1,600ユニット消費(コメント通知連携など他のYouTube API利用と合算される)。1日3〜5本程度のアップロードなら余裕がある
- **投稿ペース**: 短期間に大量投稿するとスパム判定やアルゴリズム的な抑制のリスクがあるため、1本の元動画から3〜5本を数日おきに投稿するくらいが無難
- **認証情報のバックアップ**: `data/.youtube_oauth_client.json`と`data/.youtube_oauth_token.json`はgitignore対象。ローカル環境が変わる場合はCloud Consoleでクライアント情報を再取得すれば作り直せる

## 注意点

投資・資産形成系の動画では、表現に注意する。

- 断定的な投資助言に見えないようにする
- 元動画の文脈と違う切り抜きにしない
- 数字や制度の話は公開前に人間が確認する
- 概要欄に元動画リンクを入れる
- 必要に応じて「投資判断はご自身で」系の注意書きを入れる

また、AI抽出は「盛り上がり」と「正確性」を混同しやすい。最終的な公開判断は人間が行う。

## 次のアクション

1. `fire-lab-shorts` を別リポジトリまたは別フォルダとして作成する
2. YouTube URLを1本選ぶ
3. 文字起こしと候補抽出までのプロトタイプを作る
4. 候補の当たり外れをレビューする
5. プロンプトを改善する
6. 字幕付き縦動画の自動レンダリングを追加する
