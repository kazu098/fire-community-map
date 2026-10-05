# Discord OAuthログイン実装計画 (Issue #253)

方式: 案A(Supabase Auth標準のDiscordプロバイダ + `supabase-js`)。

## 現状の要点(コード確認済み)

- フロントは `index.html` 内で `fetch(SUPABASE_URL/rest/v1/... , {apikey, Authorization: Bearer ANON_KEY})` を約40箇所直書き。`supabase-js` 未使用。
- 「自分」は `localStorage.myNickname`(`index.html` L3564〜)。
- 書き込み系RLSが anon に全開放のテーブル:
  - `member_tags`(insert/update/delete), `member_links`(insert/delete), `member_profiles`(update)
  - `member_matching_settings`(insert/update), `member_availability`(insert/delete), `member_availability_overrides`(insert/delete)
  - `community_posts`(delete), `storage.objects` の bookshelf covers(insert)
- SECURITY DEFINER RPC 経由の書き込み: `update_member_location_map`, `update_member_profile_publication`, `update_bookshelf_book_thumbnail`
- `member_profiles.discord_user_id` は列SELECT剥奪済み、`get_member_discord_user_id` RPCで1件ずつ取得。
- `middleware.js` はルート `/` の共有Basic認証のみ。

## 設計方針

1. **本人性の根拠** = `auth.users` の Discord ユーザーID(`raw_user_meta_data->>'provider_id'`)と `member_profiles.discord_user_id` の一致。
2. 新関数 `public.current_member_nickname()`(SECURITY DEFINER, STABLE)を作り、`auth.uid()` → Discord ID → `member_profiles.nickname` を解決。RLSはこの関数1つに依存させ、全ポリシーで共通化する。
3. **最終形はサイト全体をメンバー限定にする**(Discordログイン必須、Basic認証は廃止)。ただし段階移行のため、フェーズ3まで読み取りは従来通り公開、フェーズ4で閲覧RLSもメンバー限定に切り替え、同時にBasic認証を外す。
   - 補足: 現行のBasic認証が守っているのはHTMLだけで、anon keyが `index.html` に埋まっているためAPIの読み取りは実質公開状態。サイトを本当にメンバー限定にするには閲覧RLSの変更が必須。
4. Discordサーバー未参加者: `current_member_nickname()` が NULL を返す → 書き込みは全てRLSで拒否される。ログイン自体はできるが何も編集できない。UIには「FIREコミュニティのメンバーとして確認できません」を表示(別途Guild確認は不要、メンバー表との突合で足りる)。
5. 段階移行: 一括切替せず、**互換期間(フェーズ2)にanon書き込みと本人書き込みを併存**させ、確認後にanon書き込みを閉じる(フェーズ4)。

## フェーズ

### フェーズ0: 事前準備(コード外・人手)
- [ ] Discord Developer Portal でOAuthアプリ登録(Client ID/Secret発行)。誰が行うか要決定(未決事項5)。
- [ ] リダイレクトURI: `https://hchlqnsretsbhumeojdk.supabase.co/auth/v1/callback`
- [ ] Supabase Dashboard > Auth > Providers > Discord を有効化、Client ID/Secret入力。
- [ ] Auth > URL Configuration: Site URL と Redirect URLs に本番URL + Vercelプレビューを登録。
- [ ] スコープは `identify` のみ(emailは不要。プライバシー最小化)。
- [ ] 検証: テストログインして `auth.users.raw_user_meta_data` に `provider_id` が入るか確認。

### フェーズ1: データ基盤(SQLのみ・挙動変更なし)
`supabase/member_auth.sql` を新規作成:
- `current_member_nickname()` 関数。
- `discord_user_id` 未解決メンバーの対応: 2026-10時点で `member_profiles` 91件中80件が紐付け済み(未紐付け11件)。全員がDiscordユーザーのため、`sync_member_discord_ids.py` と `config/member_discord_name_map.csv` で補完して**フェーズ4前に100%にする**。専用の救済UIは作らない。ログイン方法が分からない人にはDiscordで手順を案内する(運用対応)。
- 紐付け率の事前確認クエリ: `member_profiles` のうち `discord_user_id is null` の件数。**これが多い場合はフェーズ2以降に進まず先に `config/member_discord_name_map.csv` で解消**。
- 動作確認用のテスト(SQLでJWTクレームを偽装した `set local request.jwt.claims` による当人/他人/未ログインの検証)。

### フェーズ2: フロントにログインを導入(RLSはまだ変えない)
- `supabase-js` をCDN(esm)で読み込み、`window.sb` クライアントを1つ生成(`persistSession: true`)。
- ヘルパー `authHeaders()` を新設: ログイン済みなら `Bearer <access_token>`、未ログインなら従来の ANON_KEY。`index.html` の約40箇所の `Authorization: Bearer ${SUPABASE_ANON_KEY}` を置換(書き込み系を優先、読み取りは最後でもよい)。
- UI: ヘッダーに「Discordでログイン / ログアウト」。ログイン後 `current_member_nickname()` を呼び `myNickname` をその値で上書き。ログイン済みなら `myNickname` を選び直すUIを無効化。未ログインの旧「自己申告」は互換期間のみ残す。
- `localStorage.myNickname` はログイン状態を正とし、不一致なら破棄。
- Basic認証との共存: `middleware.js` は `/` のみ対象でOAuthのコールバック(Supabase側ドメイン)に影響しない。ただしリダイレクト後に再度Basic認証が出ないことを確認。

### フェーズ3: RLS切替の準備(併存ポリシー)
新ポリシーを**追加**(既存は残す):
- `member_matching_settings` / `member_availability` / `member_availability_overrides`: `member_nickname = current_member_nickname()`
- `member_tags` / `member_links`: 同上
- `member_profiles` update: `nickname = current_member_nickname()`(列制限の grant は現行を踏襲)
- `community_posts` delete: **投稿者本人のみ**(`member_nickname = current_member_nickname()`)。管理者ロールは作らない。
  - 削除できるのは本・旅行など投稿者名を表示している種別のみ。相談系(複数人の議論スレッド、投稿者名を出さない方針)は画面から削除不可とし、✕ボタンも出さない(`canRemoveCommunityPost` を `content_type in ('book','travel') && member_nickname === myNickname` に変更)。
  - 投稿者が特定できていない投稿(`member_nickname` が空)は画面から削除不可。必要時は運営がservice-roleで処理する。
  - bookshelf(storageのcovers insert等): メンバー確認済みなら可。
- RPC(`update_member_location_map` 等): 関数内で `p_nickname = current_member_nickname()` を検証する分岐を追加。互換期間はanonも許可。
- Botのservice-role書き込み(`run_member_matching.py` 等)はRLSをバイパスするため影響なし。

### フェーズ4: anon書き込み・閲覧の閉鎖とBasic認証廃止(破壊的・要確認)
- 一定期間ログインを案内し、メンバーの大半がログインできたことを確認した後、旧「publicly insertable/updatable/deletable」ポリシーを drop。
- 全テーブルの「publicly readable」SELECTポリシーを `current_member_nickname() is not null`(メンバー確認済みのみ)に置換。
- 未ログイン時は、フロントがログイン画面(Discordログインボタンのみ)を表示し、データを取得しない。
- 上記が本番で動作確認できたら、**同じPR/リリースで** `middleware.js` のBasic認証を削除(Vercelの `BASIC_AUTH_USER/PASSWORD` 環境変数も撤去)。
- RPCの anon 許可分岐を削除。
- ロールバック手順: 旧ポリシーを再作成するSQLを `supabase/member_auth_rollback.sql` として事前に用意。

### フェーズ5: 仕上げ
- `member_matching.sql` の「no per-member auth」コメント更新、`README.md` / `docs/` に認証フローと運用手順を記載。
- 自己申告UIの削除(`index.html` L3564〜3620 周辺)。
- `scripts/sync_member_discord_ids.py` の補完を定期実行に組み込むかを検討。

## テスト計画
- SQL: 本人 / 別メンバー / ログイン済みだが未紐付け / 未ログイン × 各テーブルの insert/update/delete を `set local role authenticated` + `request.jwt.claims` で検証。
- フロント: Vercel Previewで、ログイン → 自分の設定編集 → 他人の行を編集して拒否(403/空)を確認。ログアウト後は閲覧のみ可能。
- anon key直叩きでフェーズ4後に書き込み・読み取りの両方が拒否されること(curl)。
- モバイルSafariでのリダイレクト往復(Basic認証 + OAuth)。

### フェーズ6: 秘匿情報(SSO完成後の次期開発・本計画のスコープ外、設計メモ)
SSO完成後に、本人だけが見られる情報を追加する。具体的な要件はまだ未確定のため、現時点で想定している2件のみ記す。

1. **メンバー詳細ページの非公開リンク**
   - 既存 `member_links` は公開前提(全員が読める)。非公開リンクは別テーブル `member_private_links`(`member_nickname`, `label`, `url`)を作り、RLSは `member_nickname = current_member_nickname()` の本人のみ select/insert/delete 可。もしくは `member_links` に `visibility` 列を足す案もあるが、公開RLSとの混在でミスしやすいため別テーブルを推奨。
2. **ゆるマッチングの「マッチングしたい相手」希望**
   - テーブル `member_match_wishes`(`member_nickname`, `wished_nickname`)、RLSは本人のみ。他メンバーからは存在自体が見えない。
   - マッチング実行スクリプト(`run_member_matching.py`、service-role)だけが全員分を読めるため、「相互に希望した場合に優先」などのロジックはサーバー側で完結できる。相手に希望の有無が漏れないようにする(通知文にも出さない)ことが要件。
   - 入力UIはニックネーム選択(セレクト)。

共通方針: 秘匿情報は「公開フラグ付きの列」ではなく**別テーブル+本人限定RLS**で持つ(誤公開の事故を構造的に防ぐ)。Supabaseのservice-role権限を持つ運営からは技術的に読めることはメンバーに明示する。

## ローカルでのログイン確認手順(#285)

ログイン機能は既定でオフ。`?login=1` を付けて開いたときだけ有効になる(ブラウザのlocalStorageに保存、`?login=0` で解除)。

1. **Supabase側の事前設定(1回だけ)**: Authentication > URL Configuration > Redirect URLs に `http://localhost:8000/**` を追加。Vercelプレビューで確認する場合は `https://fire-community-map-*-<チーム名>.vercel.app/**` のように、自分のプロジェクトにだけ一致するパターンを追加(`*.vercel.app` のような広い指定は避ける)。Site URL は本番URLのまま。
2. `python3 -m http.server 8000` で起動し、http://localhost:8000/index.html?login=1 を開く(Basic認証は本番のみ)。
3. 右上の「Discordでログイン」→ Discordの許可画面で許可 → 元の画面に戻る。右上に「👤 自分のニックネーム」と「ログアウト」が出れば成功。
4. 確認すること: 許可画面の文言(取得する情報)、リロード後もログイン状態が続く、ログアウトで未ログインに戻る、`#member/…` のURLを開いてログインしても同じ画面に戻る。
5. `identify` スコープだけでログインできない(メールが取れないエラーになる)場合は、`signInWithDiscord()` の `scopes` に `email` を足す。メールは `auth.users` にだけ保存され、サイトには出さない。
6. **Basic認証との共存(Vercelプレビュー/本番)**: Basic認証を通ったあと、OAuthから戻ったときに再度Basic認証が出ないこと。ブラウザは同じオリジンにBasic認証の資格情報を保持するため通常は出ない。

## リスク・注意点
- 紐付け未解決メンバーは、フェーズ4後に編集不能になる(最大のUX劣化)。フェーズ1の件数確認がゲート。
- 全RLS書き換えは一括デプロイ不可(フェーズ分割必須)。DBマイグレーションは Supabase に直接適用されるため、Vercelの自動デプロイと切り離して手順化する。
- セッション有効期限切れ時、書き込みが静かに失敗しないよう 401 を検知して再ログインに誘導する。
- Discord側でユーザーIDが変わることはない(表示名変更の影響を受けない)ので、本人性の根拠は表示名ではなくID一致のみとする。

## 未決事項(着手前に必要な判断)
1. 方式は案Aで確定してよいか。
2. ~~ログイン必須の範囲~~ → **決定済み: サイト全体をメンバー限定(ログイン必須)、Basic認証はフェーズ4完了と同時に廃止。**
3. ~~運営操作の扱い~~ → **決定済み: 投稿の削除は投稿者本人のみ(本・旅行)。相談系は削除不可。管理者ロールなし。**
4. Discord Developer Portal の登録担当。
5. ~~紐付け未解決メンバーの救済手順~~ → **決定済み: 未紐付け11件をフェーズ1で補完。それ以降は運用で案内。**

## PR分割案
1. `supabase/member_auth.sql` + 紐付け率確認(SQLのみ)
2. フロント: supabase-js導入 + ログインUI + `authHeaders()`
3. 併存ポリシー追加 + RPC更新
4. anon書き込み閉鎖(ロールバックSQL付き)
5. 自己申告UI削除とドキュメント
