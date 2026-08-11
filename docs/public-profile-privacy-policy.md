# 外部公開フラグの安全ポリシー

`member_profiles` の以下の列は、外部公開ページに個人情報を出すための明示的な許可フラグです。

- `nickname_public`
- `avatar_public`
- `self_intro_public`
- `location_public`
- `links_public`

## 絶対ルール

- 同期スクリプト、バッチ投入スクリプト、GitHub Actions、データ補完処理は、これらの外部公開フラグを自動で `true` にしてはいけない。
- 新規メンバーを登録するときも、自己紹介・タグ・アイコン・リンクを補完するときも、外部公開フラグは必ず `false` のままにする。
- 既存メンバーを補完更新するときは、既存の外部公開フラグ値を保持するだけにする。`false` を `true` に変更してはいけない。
- 外部公開フラグを `true` にできるのは、本人または管理者がメンバー一覧画面の外部公開設定で明示的にONにした場合だけ。

## 実装時の必須確認

外部公開フラグに触る変更を入れる場合は、必ず以下を通す。

```bash
python3 scripts/check_public_profile_privacy_guard.py
```

このチェックは、新規プロフィールpayloadに自己紹介・アイコン・リンクが含まれていても、外部公開フラグがすべて `false` のままであることを検証する。

## DB側の防御

- `member_profiles` には `prevent_implicit_public_profile_publication` トリガーを置き、通常の `INSERT` / `UPDATE` で外部公開フラグが `false` から `true` になる変更を拒否する。
- メンバー一覧画面の外部公開設定だけは、専用RPC `update_member_profile_publication` を通して明示的にON/OFFする。
- 同期スクリプトやバッチ投入スクリプトは、外部公開フラグをONにする専用RPCを呼んではいけない。
- 新しい同期処理を追加するときは、公開フラグをpayloadに含めないか、既存値維持/新規`false`のみ許可する。`true` 固定や `bool(avatar_url)` のような自動判定は禁止。
