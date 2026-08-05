# Googleフォーム送信時のメンバー自動追加

フォーム回答シートに新規入力が来たタイミングで GitHub Actions を起動し、既存の `scripts/sync_member_location_deltas.py` で Supabase に同期する。

## 1. GitHub Secrets

Repository Settings > Secrets and variables > Actions に以下を登録する。

- `DISCORD_BOT_TOKEN`
- `DISCORD_GUILD_ID`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## 2. GitHub Token

Apps Script から GitHub Actions の `workflow_dispatch` API を呼ぶため、GitHub の fine-grained personal access token を作る。

- Repository access: `kazu098/fire-community-map`
- Repository permissions: `Actions` を `Read and write`
- 有効期限は運用に合わせて設定

作成した token は Apps Script の Script Properties に保存する。

## 3. Apps Script

フォーム回答スプレッドシートで Extensions > Apps Script を開き、以下を貼る。

```javascript
const OWNER = 'kazu098';
const REPO = 'fire-community-map';
const WORKFLOW_ID = 'sync-member-form-submit.yml';
const REF = 'main';

function setupMemberSubmitSync() {
  const token = Browser.inputBox('GitHub token');
  PropertiesService.getScriptProperties().setProperty('GITHUB_TOKEN', token);

  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'onMemberFormSubmit')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger('onMemberFormSubmit')
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onFormSubmit()
    .create();
}

function onMemberFormSubmit(e) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;

  try {
    dispatchMemberSync();
  } finally {
    lock.releaseLock();
  }
}

function dispatchMemberSync() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('GITHUB_TOKEN is not set. Run setupMemberSubmitSync first.');

  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_ID}/dispatches`;

  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    payload: JSON.stringify({
      ref: REF,
      inputs: {
        sheet_url: sheet.getUrl(),
        sheet_name: 'Form Responses 1',
        update_existing: 'false',
        refresh_avatars: 'false',
        dry_run: 'false',
      },
    }),
    muteHttpExceptions: true,
  });

  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error(`GitHub workflow dispatch failed: ${code} ${response.getContentText()}`);
  }
}
```

## 4. 初回設定

Apps Script の `setupMemberSubmitSync` を1回だけ実行し、GitHub token を入力する。権限確認が出たら承認する。

以後はフォーム送信ごとに `Sync member form submit` workflow が起動する。

## 注意

- 回答シートは workflow から公開CSVとして読める必要がある。非公開運用にする場合は、Apps Script 側で回答行を webhook payload として送る別実装にする。
- 同時送信があっても workflow 側は `concurrency` で直列化する。
- 住所判定不能、Discordアバター未一致、既存メンバーの住所変更検知などは GitHub Issue に確認項目として出す。
