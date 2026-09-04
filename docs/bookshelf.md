# 本棚タブ(F研公式本・メンバー著書)

サイトの「本棚」タブに、FIRE研究所公式本とメンバーが出版した本を本棚レイアウトで表示する。

## データ

`supabase/bookshelf_books.sql` で作成する `public.bookshelf_books` テーブルに保持する。`member_tags`/`member_links` と違い、anon keyでの書き込みは許可しない(読み取りのみ公開)。掲載本の追加・削除は運営が `scripts/load_bookshelf_books.py` を実行して行う。

- `source`: `fire_lab`(FIRE研究所公式本) / `member`(メンバー著書)
- `member_nickname`: メンバー著書の場合、`member_profiles.nickname` と一致させる
- `amazon_url`: Amazon商品ページ(短縮URL可)。unique制約あり
- `thumbnail_url`: 表紙画像。`bookshelf-covers` Storageバケットの公開URL(取得方法は下記)。未設定の本は書名を表示したスパイン風カードで代替表示
- `drive_pdf_url`: 任意。Google DriveのPDFへのリンク。設定するとカードに「PDF」リンクが表示される
- `member_nickname` が設定されている本は、著者名がメンバー詳細画面へのリンクになる

## 初期データ

- FIRE研究所公式本4冊は `firekenkyujo.com/books/` から転記
- メンバー著書は `member_links` に登録されたAmazonリンクのうち、本人の著書と判断できるものを手作業で選定(自動抽出ではない — ラベルが商品紹介記事など著書と断定できないものは対象外)
- 正式なタイトルはAmazon商品ページ(ログイン済みブラウザで開いて確認。`curl`等の非ブラウザ手段はAmazon側のbot対策でブロックされる)から転記している
- Google Driveの内部共有フォルダ(PDF)にある本のうち、まだ掲載されていないものはAmazon内検索で該当書籍を探して追加する。PDFのファイル名とAmazon上の正式タイトルは必ずしも一致しない(例: 同じ本でもPDFは旧タイトル)ため、著者名や内容から同一書籍かどうかを判断する

## 反映

```bash
python3 scripts/load_bookshelf_books.py --dry-run   # 内容確認
python3 scripts/load_bookshelf_books.py              # Supabaseへ反映
```

Supabase側に `bookshelf_books.sql` を先に一度適用しておく必要がある(SQL Editorで実行)。

## サムネイル画像

各本のAmazon商品ページの表紙画像(画像CDN: `m.media-amazon.com`)から取得し、`bookshelf-covers` Storageバケットにアップロード済み。`scripts/load_bookshelf_books.py` の各エントリの `thumbnail_url` を更新して再実行すれば差し替えられる。

なお、メンバーがブラウザから直接サムネイルをアップロードできるRPC(`update_bookshelf_book_thumbnail`)とStorageの匿名アップロードポリシーは検討段階で本番に適用したが、Amazon側から表紙画像を取得できたため現状UIからは呼び出していない(未使用のまま残置)。
