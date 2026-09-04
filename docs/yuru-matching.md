# ゆるマッチング(availability-based random matching)

空いている曜日・時間帯を登録したメンバー同士を、興味・タグの近さではなくランダムにペアリングする「気軽に話してみる」きっかけ作り機能。GitHub issue #76 の設計を土台にしている。

## データモデル(`supabase/member_matching.sql`)

- `member_matching_settings`: メンバーごとの参加フラグ(`opted_in`)とマッチング頻度(`interval_days`: 3/7/14/30日)。`last_matched_at` はバッチ(service role)のみが更新する。
- `member_availability`: 曜日(`day_of_week`)×時間帯(`morning`/`afternoon`/`evening`)の自己申告スロット。
- `member_matches`: マッチング結果の履歴。再マッチングのクールダウン判定(60日)と、Discordへの投稿状況(`discord_message_id`)の監査ログを兼ねる。

既存の `member_tags`/`member_links` と同様オープン編集(anon write可)だが、書き込み範囲は列単位で絞ってある。`opted_in`/`interval_days` の更新をPostgRESTの `resolution=merge-duplicates` upsertで行うため、conflict対象列(`member_nickname`)と、`set_updated_at` トリガーが書き込む `updated_at` にも `UPDATE` 権限が必要な点に注意(値は実質変わらないが、Postgresは列単位の権限チェックをトリガー代入にも適用する)。

## UI(`index.html`)

メンバー詳細画面の「ゆるマッチング」セクション(`buildMatchingSection`)で、参加ON/OFFトグル・頻度セレクト・曜日×時間帯の○×グリッドを自己編集できる。

## バッチ(`scripts/run_member_matching.py`)

`interval_days` が経過して再マッチング対象になったopted-inメンバーを、空き時間が重なる相手とランダムにペアリングし、`member_matches` に記録した上でDiscordの専用チャンネルに投稿する。

- `--dry-run`: Supabaseへの書き込み・Discord投稿なしでマッチング結果を確認
- `--post-to-discord`: `DISCORD_MATCHING_CHANNEL_ID`/`DISCORD_BOT_TOKEN` が未設定ならDiscord投稿だけスキップ(マッチング自体は記録される)
- `--seed`: 乱数シードを固定して再現可能なdry-runを行う

アナウンス文はマスコット「ふぁいにゃ」の一人称で書く([docs/fainya-persona.md](./fainya-persona.md)参照)。あわせて、マッチした二人の「相談できること」×「知りたいこと」の一致や、共通の興味・投資スタイルなどのタグ、自己紹介文の有無から話題のヒントを一文添える(`build_topic_suggestion`)。該当がなければヒント行は省略する。

再マッチングのクールダウンは60日固定(`COOLDOWN_DAYS`)。実行はcronなどで定期的に(例: 日次)`run_member_matching.py --post-to-discord` を呼ぶ想定。
