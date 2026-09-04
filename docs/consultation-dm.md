# 相談してみる(consultation DM draft)

メンバー詳細画面から、気になった相手にDiscordのDMで連絡を取るきっかけを作る機能。「何を相談したいか分からない」まま唐突にDMを送るのは気が引ける、という声を踏まえ、**自動送信はせず**、下書き文の生成とDiscordのDM画面を開くリンクの提示までに留めている。

## できること

- メンバー詳細画面の「相談してみる」セクションのボタンを押すと、その相手向けの下書き文が表示される
- 下書きは「📋 下書きをコピー」でクリップボードにコピーできる(実際の送信は本人がDiscord上で行う)
- 「DiscordのDMを開く ↗」で `https://discord.com/users/{discord_user_id}` を新しいタブで開く(Discordは他サービスと違いDM本文をURLで事前入力できないため、コピー→貼り付けは手動)

## 下書き文の生成(`buildConsultationReason` / `buildConsultationDraft`, index.html)

`scripts/run_member_matching.py` の話題生成ロジック(ゆるマッチングのアナウンス内「盛り上がりそうな話題」)と同じ発想で、次の優先順位で「相談する理由」を1つ選ぶ(LLMは使わない、決定的なルールベース):

1. 自分(`myNickname` で選択中の場合)の「相談できること」と相手の「知りたいこと」の一致
2. 相手の「相談できること」と自分の「知りたいこと」の一致
3. 興味・投資スタイル・活動/部活・得意なこと・MBTI・FIREタイプのいずれかで自分と相手に共通するタグ
4. (`myNickname` 未設定、または上記すべて該当なしの場合)相手の「相談できること」タグ
5. 相手の「興味・趣味」タグ
6. 相手の自己紹介文に出てくるキーワード(`CONSULTATION_INTRO_KEYWORDS`)
7. 該当なし → 「プロフィールを拝見してご連絡しました。」という一般的な書き出し

## Discord DM リンクの仕組み

`member_profiles.discord_user_id` (`supabase/member_discord_ids.sql`) にメンバーごとのDiscordユーザーIDを保持している。member_profilesは元々「Discordユーザーは保存しない」方針だったが、このDMリンク機能のために方針を変更した。書き込みはservice roleのみ(anon/authenticatedへのUPDATE権限は付与していない)。

`scripts/sync_member_discord_ids.py` が `scripts/run_member_matching.py` のDiscordメンション解決ロジック(ギルドメンバー一覧の表示名突合 + `config/member_discord_name_map.csv` によるフォールバック解決)を再利用してニックネームごとに解決し、`member_profiles.discord_user_id` を更新する。解決できなかったメンバーは値を変更しない(既存値があれば残す/なければnullのまま)。GitHub Actions (`.github/workflows/sync-member-discord-ids.yml`) で毎日05:15 JSTに実行し、ゆるマッチングバッチ(05:30 JST)より前に最新化しておく。

解決できなかったメンバーの詳細画面では、DMリンクの代わりに「Discord上でニックネームを検索してDMを送ってください」という案内を表示する。
