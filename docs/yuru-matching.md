# ゆるマッチング(availability-based random matching)

空いている曜日・時間帯を登録したメンバー同士を、興味・タグの近さではなくランダムにグルーピングする「気軽に話してみる」きっかけ作り機能。GitHub issue #76 の設計を土台にしている。デフォルトのグループサイズは3人(条件が合わなければ2人にフォールバック)。

## データモデル(`supabase/member_matching.sql`)

- `member_matching_settings`: メンバーごとの参加フラグ(`opted_in`)とマッチング頻度(`interval_days`: 2/3/7/14/30日)。`last_matched_at` はバッチ(service role)のみが更新する。
- `member_availability`: 曜日(`day_of_week`)×時間帯(`morning`/`afternoon`/`evening`)の自己申告スロット。
- `member_match_groups` / `member_match_group_members`: マッチング結果の履歴。1グループ1行(`member_match_groups`)+所属メンバーの中間テーブル(`member_match_group_members`)という構成にしているのは、固定の`member_a`/`member_b`列だとグループサイズを変える度にスキーマ変更が必要になるため。再マッチングのクールダウン判定(60日、グループ内の全2人組み合わせが対象)と、Discordへの投稿状況(`discord_message_id`)の監査ログを兼ねる。

既存の `member_tags`/`member_links` と同様オープン編集(anon write可)だが、書き込み範囲は列単位で絞ってある。`opted_in`/`interval_days` の更新をPostgRESTの `resolution=merge-duplicates` upsertで行うため、conflict対象列(`member_nickname`)と、`set_updated_at` トリガーが書き込む `updated_at` にも `UPDATE` 権限が必要な点に注意(値は実質変わらないが、Postgresは列単位の権限チェックをトリガー代入にも適用する)。

## UI(`index.html`)

メンバー詳細画面の「ゆるマッチング」セクション(`buildMatchingSection`)で、参加ON/OFFトグル・頻度セレクト・曜日×時間帯の○×グリッドを自己編集できる。

## バッチ(`scripts/run_member_matching.py`)

`interval_days` が経過して再マッチング対象になったopted-inメンバーを、空き時間が重なる相手とランダムにグルーピング(`run_matching`、デフォルト最大3人。3人目の候補が見つからなければ2人ペアにフォールバック)し、`member_match_groups`/`member_match_group_members` に記録した上でDiscordの専用チャンネルに投稿する。

- `--dry-run`: Supabaseへの書き込み・Discord投稿なしでマッチング結果を確認
- `--post-to-discord`: `DISCORD_MATCHING_CHANNEL_ID`/`DISCORD_BOT_TOKEN` が未設定ならDiscord投稿だけスキップ(マッチング自体は記録される)
- `--seed`: 乱数シードを固定して再現可能なdry-runを行う

### アナウンス文と話題のヒント

アナウンス文はマスコット「ふぁいにゃ」の一人称で書く([docs/fainya-persona.md](./fainya-persona.md)参照)。名前部分は実際にDiscordの通知が飛ぶ`<@user_id>`メンションにしている(`fetch_guild_member_ids_by_display_name`でギルドメンバーの表示名を取得し、サイトのニックネームと突き合わせる。絵文字などの装飾差分で一致しない場合は`config/member_discord_name_map.csv`(scripts/match_discord_avatars.pyと共用)でのフォールバック解決も試みる。それでも解決できなければ通知なしの太字表示にフォールバックする)。3人グループの場合の例:

```
🐾 かず さん、みかん さん、さとりーまん さんがマッチしましたにゃ！
みなさんとも「土曜午前」が空いているみたいなので、🙏 よければ集まってお話ししてみてください。（開催するかどうかはみなさんにお任せします）

💡 盛り上がりそうな話題:
- (全員) みんなnoteをやっているみたいなので、記事を見せ合うのも面白そうです
- (かずさん×みかんさん) 共通の興味「読書」の話で盛り上がれそうです
- (みかんさん×さとりーまんさん) 共通の活動・部活「YouTube運営チーム」の話で盛り上がれそうです
```

「にゃ」はふぁいにゃの語尾アクセントとして冒頭の一文にだけ使い、話題の箇条書きや詳細説明は素の丁寧語(です・ます)にしている([docs/fainya-persona.md](./fainya-persona.md)の「全文にゃにゃしない」ルールに合わせた調整)。

話題のヒントは2種類を両方出す(`build_topic_suggestion` / `pairwise_topics`):

- **全員共通の話題**(`(全員)` ラベル): グループ全員に共通する話題が1つあれば表示
- **2人組ごとの話題**: グループ内の全2人組み合わせについて個別に話題を探し、全員共通の話題と重複しないものだけ列挙

3人グループでも「全員が話せる話題」だけでなく「2人が盛り上がっているのを1人が聞く」という組み合わせも楽しめるよう、2人組の話題は全員共通の話題があるかどうかに関わらずデフォルトで出す(2人ペアにフォールバックした場合は、全員=2人組なので重複を避けて全員の行だけ表示)。

話題は次の順で候補を評価し、最初に見つかったものを採用する(該当が一つもなければその行自体を省略):

1. 「相談できること」×「知りたいこと」の一致(片方が答えられそうな話題)
2. 興味・投資スタイル・活動/部活・得意なこと・MBTI・FIREタイプのいずれかで共通するタグ
3. 自己紹介文に共通して出てくるキーワード(`INTRO_TOPIC_KEYWORDS`。タグ化されていない話題を拾うためのゆるいテキスト一致)
4. 全員がnoteを書いている、などの軽い共通点
5. 全員が同じ都道府県在住
6. 全員がまだアイコン未設定、のようなくすっと笑える偶然
7. どれにも該当しないが自己紹介文はある → 「意外な共通点が見つかるかも」という一般的な一文

「アイコンが似ている」のような実際の画像類似判定はまだやっていない(6番はあくまで「全員アイコン未設定」という取れる範囲のネタ)。

再マッチングのクールダウンは60日固定(`COOLDOWN_DAYS`)。実行は`.github/workflows/run-member-matching.yml`が毎日9時・12時・19時(JST)の3回`run_member_matching.py --post-to-discord`を呼ぶ。早朝5:30の1日1回だと就寝中に通知が届いてしまうため、日中3回に分散している。各回、その時点でinterval_days経過済み(マッチング対象)の人がいなければ何も投稿しない(no-op)ので、結果的に「まとまった人数を1日1回一気に投稿」ではなく「対象になった人がその都度ぽつぽつ投稿される」形になる。
