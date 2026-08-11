# Googleフォーム送信時のメンバー自動追加

フォーム回答シートに新規入力が来たタイミングで GitHub Actions を起動し、`scripts/sync_member_profile_form_deltas.py` で Supabase の `member_profiles` / `member_tags` に同期する。
フォームからはニックネームだけを受け取り、最新のフォーム送信行だけを対象にする。新規メンバーだけ Discord の自己紹介チャンネルを参照して、自己紹介文・アイコン・居住地・タグを補完する。

Apps Script から同期に必要な最小CSVを送るため、回答シートを公開共有にする必要はない。

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

作成した token は Apps Script の Project Settings > Script properties に保存する。

- Property: `GITHUB_TOKEN`
- Value: 作成した GitHub token

## 3. Apps Script

フォーム回答スプレッドシートで Extensions > Apps Script を開き、以下を貼る。

```javascript
const OWNER = 'kazu098';
const REPO = 'fire-community-map';
const WORKFLOW_ID = 'sync-member-form-submit.yml';
const REF = 'main';

function setupMemberSubmitSync() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Set GITHUB_TOKEN in Script properties first.');

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
  const responseSheet = sheet.getSheetByName('Form Responses 1');
  if (!responseSheet) throw new Error('Form Responses 1 sheet was not found.');

  const membersCsvB64 = buildMembersCsvB64(responseSheet);
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
        members_csv_b64: membersCsvB64,
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

function buildMembersCsvB64(responseSheet) {
  const lastRow = responseSheet.getLastRow();
  const lastColumn = responseSheet.getLastColumn();
  if (lastRow < 1) throw new Error('Response sheet is empty.');
  if (lastColumn < 2) throw new Error('Response sheet must include at least timestamp and nickname columns.');

  // sync_member_profile_form_deltas.py reads the nickname from the matching header
  // or column B, and auto-detects profile/tag/link columns from the header row.
  const values = responseSheet.getRange(1, 1, lastRow, lastColumn).getDisplayValues();
  const csv = values.map(row => row.map(csvEscape).join(',')).join('\n') + '\n';
  return Utilities.base64Encode(csv, Utilities.Charset.UTF_8);
}

function csvEscape(value) {
  const text = String(value ?? '');
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}
```

## 4. 初回設定

Apps Script の Project Settings > Script properties に `GITHUB_TOKEN` を保存したあと、`setupMemberSubmitSync` を1回だけ実行する。権限確認が出たら承認する。

以後はフォーム送信ごとに `Sync member form submit` workflow が起動する。

## 注意

- 同時送信があっても workflow 側は `concurrency` で直列化する。
- フォーム回答は、新規メンバーだけ Discord 自己紹介から判定できる自己紹介・居住地・タグを `member_profiles` / `member_tags` に同期する。外部公開フラグは自動でONにしない。
- 外部公開フラグの扱いは [外部公開フラグの安全ポリシー](./public-profile-privacy-policy.md) に従う。
- Apps Script は回答シート全体のCSVを送るが、workflow は `--latest-only` で最後の回答行だけ処理する。過去行の表記ゆれや重複回答は毎回の issue には出さない。
- 既存メンバーはデフォルトでは更新しない。明示的に `update_existing: 'true'` を渡した時だけ更新対象にする。
- 旧処理で名前だけ作られた不完全な既存プロフィールは、最新送信行に限って Discord 自己紹介から補完する。
- Discord自己紹介が見つからず、フォーム側にもタグ・自己紹介・居住地・リンク列がない場合は、名前だけの空プロフィールを作らず issue に保留内容を出す。
- 自己紹介・居住地・リンクの公開フラグは、該当値がある場合だけONにする。アイコン公開は既存 `avatar_url` がある場合だけONにする。
- 住所判定不能、Discordアバター未一致、既存メンバーの住所変更検知などは GitHub Issue に確認項目として出す。
- GitHub Actions `workflow_dispatch` の入力サイズ上限に近づくほど回答数が増えた場合は、Apps Script から中継APIへ送る方式に切り替える。
