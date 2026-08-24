# Googleフォーム送信時の自動化(廃止)

以前はフォーム回答シートに新規入力が来たタイミングで Apps Script が GitHub Actions (`sync-member-form-submit.yml`) を自動起動し、Supabase の `member_profiles` / `member_tags` / `member_links` に自動反映していた。

外部公開フラグが意図せずON/OFFされる不具合が繰り返し発生し、個人情報漏えいリスクが高いため、この自動化は**廃止**した。新規メンバーの登録リクエストはGoogleフォームの標準通知で運用者に届くので、それを見て手動で対応する運用に戻す。GitHub Issueの自動作成も行わない。

## 廃止に伴う対応

- Apps Script側: フォーム回答スプレッドシートの Extensions > Apps Script を開き、`onMemberFormSubmit` トリガーを削除する（Apps Scriptエディタの左メニュー「トリガー」から削除、または `ScriptApp.getProjectTriggers()` を列挙して `onMemberFormSubmit` ハンドラのトリガーを `deleteTrigger` する）。このリポジトリからは操作できないため、運用者が手動で行うこと。
- GitHub Actions側: `sync-member-form-submit.yml` は `workflow_dispatch` のみで起動する（自動トリガーなし）。Supabaseへの書き込みは行わず、`--dry-run` で候補をレポート（`tmp/member_profile_form_sync_report.json` をartifactにアップロード）するだけに変更済み。GitHub Issueも作成しない。
- 新規メンバーをmember_profilesに反映する場合は、レポートの内容を確認したうえで手動で反映するか、必要に応じて `scripts/sync_member_profile_form_deltas.py` をローカルから実行する（`--dry-run` を外せば書き込みも可能だが、[外部公開フラグの安全ポリシー](./public-profile-privacy-policy.md) を必ず確認すること）。

## 参考: workflowを手動実行する場合

GitHub Actionsの「Sync member form submit」を Actions タブから手動実行(workflow_dispatch)すると、指定したシートの最新回答行だけを対象に候補レポートを生成できる。Supabaseへの書き込みは行われない。
