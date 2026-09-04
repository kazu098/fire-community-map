# コミュニティ投稿(読んだ本・旅行・質問相談・note・お金の相談・介護医療・子育て・不動産)の収集

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

## コミュニティ投稿候補の定期確認

`.github/workflows/sync-community-content.yml` で毎日 05:30 JST に、前回リポジトリへ反映された `data/community_posts_sync_state.json` 以降の差分だけを取得します。処理後は同期stateを自動commitするため、同じ差分を毎日繰り返しIssue化しません。

- `こんな本読みました` は、本文から本タイトルを抽出でき、投稿者が `member_profiles` に一致する場合だけ自動でSupabaseへ反映します。
- 読書投稿でも、タイトルを本文から確定できないもの、投稿者が未マッピングのもの、短文返信っぽいものはGitHub Issueに回します。
- 旅行/グルメ系は、画像あり・場所推定あり・外食/旅先グルメ判定ありのものだけ自動で `data/travel_posts.json` とSupabaseへ反映します。画像や場所が足りないものはIssueに回します。
- お金・介護/医療・子育て・不動産・質問相談は、内容確認が必要な「暮らしの知恵」候補としてGitHub Issueにまとめます。
- 旅行グルメで場所推定に失敗した投稿や、画像なしの投稿は、地図追加候補としてIssueで確認します。
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
python3 scripts/sync_travel_posts.py
python3 scripts/load_travel_posts_to_community_posts.py
python3 scripts/build_community_content_review_report.py \
  --raw tmp/community_posts_raw.json \
  --curated tmp/community_posts_book_auto.json \
  --travel-posts data/travel_posts.json \
  --output tmp/community_content_review_needed.md \
  --count-output tmp/community_content_review_count.txt
```

承認後は、暮らしの知恵と例外扱いの読書投稿は `tmp/community_posts_curated.json` を整えて `scripts/load_community_posts.py` でSupabaseへ反映します。旅行グルメは自動反映対象外になったものだけ、場所エイリアス追加や投稿者マッピング追加をしてから再実行します。
