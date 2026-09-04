# 会員データパイプライン

Googleフォームの回答から、会員マップに表示するデータ(居住地・アバター)をSupabaseへ投入するまでの一連の処理。

## Discordアバター突合

Googleフォーム回答のニックネームとDiscordサーバー上の表示名を完全一致で突合し、アバター候補をJSONに出力します。

```bash
python3 scripts/match_discord_avatars.py \
  --members-csv path/to/form_responses.csv \
  --output tmp/member_avatar_matches.json
```

完全一致しないが本人確認済みの表示名差分は、`config/member_discord_name_map.csv` に `form_nickname,discord_display_name` 形式で追加します。出力の `nickname` はGoogleフォーム側の値を維持し、Discord表示名はアバター照合にだけ使います。

`.env` には以下を設定します。

```env
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
GOOGLE_SHEET_ID=...
GOOGLE_SHEET_NAME=Form Responses 1
```

Google Sheetsが認証必須の場合、まず回答シートをCSVとしてエクスポートし、`--members-csv` に渡します。公開CSVとして読めるシートであれば、`--members-csv` を省略すると `GOOGLE_SHEET_ID` / `GOOGLE_SHEET_NAME` から直接読み込みます。

## 住所正規化

Googleフォームの自由入力住所を、Supabase投入用の `location_text`, `prefecture`, `municipality_optional`, `location_level`, `lat`, `lng`, `map_lat`, `map_lng` に正規化します。

```bash
python3 scripts/normalize_member_locations.py \
  --members-csv path/to/form_responses.csv \
  --output-json tmp/member_locations_normalized.json \
  --output-csv tmp/member_locations_normalized.csv
```

`lat` / `lng` は元入力を正規化した代表座標です。同じ代表座標に複数人が集まる場合は、地図表示用の `map_lat` / `map_lng` を少しずらして出力します。DBには両方保存し、地図マーカーは `map_lat` / `map_lng` を使います。

表記ゆれや地方名は `config/location_aliases.csv` で補完します。都道府県のみの入力は `config/prefecture_centroids.csv` の代表座標を使い、市区町村はGeoloniaの公開住所データから代表点を計算します。

## アバターStorage保存

Discordアバター突合結果から画像をダウンロードし、Supabase Storageの `member-avatars` bucketへ保存します。まず保存予定パスだけ確認する場合はdry-runを使います。

```bash
python3 scripts/upload_member_avatars.py \
  --matches tmp/member_avatar_matches.json \
  --output tmp/member_avatar_storage_paths.json \
  --dry-run
```

実アップロード時は `.env` に以下を設定します。

```env
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
```

bucket作成も含める場合:

```bash
python3 scripts/upload_member_avatars.py \
  --matches tmp/member_avatar_matches.json \
  --output tmp/member_avatar_storage_paths.json \
  --create-bucket
```

Storage pathにはDiscordユーザーIDを含めません。出力JSONの `avatar_path` を `member_locations.avatar_path` に保存します。

## Googleフォーム回答の差分同期

Googleフォーム回答シートから新しく追加されたメンバーだけをSupabaseへ追加します。まずdry-runで対象件数を確認します。

フォーム送信時点で自動同期したい場合は、GitHub Actions と Apps Script を使う [Googleフォーム送信時のメンバー自動追加](./member-form-submit-automation.md) を参照してください。

```bash
python3 scripts/sync_member_location_deltas.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/1PWU_Kx-bRJphF2KONPssu5DmxhlQEXmKHCwu9DaWK00/edit?usp=sharing" \
  --dry-run
```

問題なければ `--dry-run` を外して実行します。

```bash
python3 scripts/sync_member_location_deltas.py \
  --sheet-url "https://docs.google.com/spreadsheets/d/1PWU_Kx-bRJphF2KONPssu5DmxhlQEXmKHCwu9DaWK00/edit?usp=sharing"
```

既存メンバーの住所変更も反映したい場合だけ、`--update-existing` を付けます。通常の追加運用では付けません。

Google Sheetが公開CSVとして読めない場合は、フォーム回答をCSVでエクスポートして `--members-csv path/to/form_responses.csv` を渡します。
