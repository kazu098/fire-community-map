# ゆるマッチングの日程調整・一時通話部屋

itチームチャンネルでのmemeto0531さんの提案(2026-09-05、[該当メッセージ](https://discord.com/channels/1389921372683112539/1514597598357491742/1545607540392460389))を反映。マッチング成立後、日程調整から当日の通話まで極力Discord内で完結させる。

「マッチする → 行ける日を押す → 日程が決まる → 当日話す」

## データモデル(`supabase/member_match_schedules.sql`)

`member_match_groups`(1グループ1行)に対して1:1で紐づく`member_match_schedules`。`member_match_groups`と同様、サービスロールのみ書き込み可能な監査テーブル(anonは読み取りのみ)。

- `proposed_dates`: 提案した3つの候補日時(`timestamptz[]`)
- `discord_message_id`: 候補日を1️⃣2️⃣3️⃣のリアクションで投票してもらう投稿(元のマッチング告知とは別メッセージ)
- `status`: `proposed`(投票受付中) → `confirmed`(開催決定) または `expired`(どの候補も3人集まらないまま候補日をすべて過ぎた)
- `confirmed_date`/`confirmed_reaction_count`: 決定した日時と、その時点の反応者数
- `voice_channel_id`/`voice_channel_deleted_at`: 開催決定時に作る一時ボイスチャンネルと、その削除記録

## 日程提案(`scripts/run_member_matching.py`)

マッチング告知を投稿した直後、同じグループの共通曜日・時間帯から次の3回分の候補日時を算出し(`next_occurrences`)、別メッセージとして投稿・1️⃣2️⃣3️⃣のリアクションを付ける。

- 時間帯(`time_slot`)は空き時間として「午前/午後/夜」の粒度でしか登録されていないため、候補日時を出す際は`SLOT_TIMES`(午前10:00・午後14:00・夜21:00 JST)で具体的な時刻に変換する
- 直近すぎる候補(1日以内)は次の週にずらす(前日夜に届いて翌朝が候補、のような窮屈な提案を避けるため)

## 開催決定・一時通話部屋(`scripts/process_member_match_schedules.py`)

`run_member_matching.py`の直後に実行する想定(同じワークフロー内の別ステップ)。2つの処理を行う。

1. **確定判定**: `status=proposed`の各行について、3つの候補日に対応するリアクションを取得し、**マッチしたグループのメンバーだけ**が反応した数を数える(ボット自身のリアクションや無関係な人の反応は数えない)。いずれかの候補が`SCHEDULE_CONFIRM_THRESHOLD`(3人、4人グループ中3人)に達したら、最多反応(同数なら早い日程)の候補で確定。「🎉 開催決定！」を投稿し、そのグループだけが入れる一時ボイスチャンネルを作成する(`VOICE_CHANNEL_PERMISSION_BITS`で`@everyone`を拒否、グループメンバーだけ許可)。どの候補も届かないまま最後の候補日を過ぎたら`expired`にする(通知なし。オプトイン機能なので静かに終わらせる設計)。
2. **一時通話部屋の削除**: `status=confirmed`かつ`voice_channel_id`があり未削除の行について、開催予定時刻から`VOICE_CHANNEL_CLEANUP_BUFFER_HOURS`(4時間)経過していればチャンネルを削除する。

### ボイスチャンネル作成に必要な権限

チャンネルの作成・削除には、ボットのロールに **チャンネルの管理(Manage Channels)** 権限がDiscordサーバー側で付与されている必要がある。付与されていない場合、`create_voice_channel`は403で失敗するが、`process_member_match_schedules.py`はこれを検知して**日程の確定自体は続行**し、通話部屋の案内なしで「🎉 開催決定！」だけを投稿する(スクリプトは落とさない)。一時通話部屋機能を使うには、Discordサーバーの設定でボットロールに「チャンネルの管理」権限を付与する必要がある。

## 実行タイミング

`.github/workflows/run-member-matching.yml`が、マッチングバッチの直後に`process_member_match_schedules.py`を実行する(9時・12時・19時 JSTの3回)。候補日の投票は最短でも1日、最長で3週間弱の猶予があるため、この頻度で十分。
