# note用のF研通信下書き生成

F研通信のような月次・隔週の活動報告は、Discordから収集済みのJSONを元にMarkdown下書きを生成できます。noteへの投稿やAI API呼び出しは行わず、編集者が確認して貼り付けるための素材を作ります。本文は募集・告知ではなく、開催済みの活動記録として過去形でまとめます。

先にイベント系・投稿系のDiscord同期を実行します。

```bash
python3 scripts/fetch_community_events.py
python3 scripts/fetch_community_posts.py
```

月2回運用のnote貼り付け用下書き:

```bash
# 1日0:00〜15日12:00分。
python3 scripts/generate_note_activity_draft.py \
  --month 2026-08 \
  --half first
```

```bash
# 15日12:00直後〜月末12:00分。
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

月2回運用では、イベント系だけでなく `tmp/community_posts_raw.json` の旅行・本・お金の話・介護/医療なども本文候補に含めます。Discord添付画像が取れる場合だけ `画像候補:` として残します。告知文・予定概要だけで開催後の具体情報が取れない活動は、薄い章になりやすいため自動的に落とすことがあります。

`--template editorial --delivery paste` では、画像URLを除いた本文が5,000字未満、参加者数表記が残っている、カテゴリ名だけの見出しが残っている、などの場合に `Quality warning:` を出して終了コード2で失敗します。警告が出た場合は、取得データが足りないか、材料のある章を深掘りするための curated 情報が不足している可能性があります。調査用に未達でもファイルだけ作りたい場合は `--allow-quality-warnings` を付けます。

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

自動実行する場合は、毎月15日12:00以降に `--half first`、月末12:00以降に同月の `--half second` を実行します。GitHub Actions化する場合も、最終的には生成されたMarkdownを投稿担当者が確認してからnoteへ貼り付けます。
