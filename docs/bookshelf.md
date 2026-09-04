# 本棚タブ(F研公式本・メンバー著書)

サイトの「本棚」タブに、FIRE研究所公式本とメンバーが出版した本を本棚レイアウトで表示する。

## データ

`supabase/bookshelf_books.sql` で作成する `public.bookshelf_books` テーブルに保持する。`member_tags`/`member_links` と違い、anon keyでの書き込みは許可しない(読み取りのみ公開)。掲載本の追加・削除は運営が `scripts/load_bookshelf_books.py` を実行して行う。

- `source`: `fire_lab`(FIRE研究所公式本) / `member`(メンバー著書)
- `member_nickname`: メンバー著書の場合、`member_profiles.nickname` と一致させる
- `amazon_url`: Amazon商品ページ(短縮URL可)。unique制約あり
- `thumbnail_url`: 表紙画像。Amazon側のbot対策で自動取得できないため、Supabase Storageに手動アップロードした画像URLを設定する(未設定の間は書名を表示したスパイン風カードで代替表示)
- `drive_pdf_url`: 任意。Google Drive等のPDFへのリンク。設定するとカードに「PDF」リンクが表示される

## 初期データ

- FIRE研究所公式本4冊は `firekenkyujo.com/books/` から転記
- メンバー著書は `member_links` に登録されたAmazonリンクのうち、本人の著書と判断できるものを手作業で選定(自動抽出ではない — ラベルが商品紹介記事など著書と断定できないものは対象外)
- タイトルが特定できなかった本は `scripts/load_bookshelf_books.py` の `MEMBER_BOOKS` 内で `title: None` のまま残し、投入時にスキップされる。本人に確認できたらタイトルを埋めて再実行する

## 反映

```bash
python3 scripts/load_bookshelf_books.py --dry-run   # 内容確認
python3 scripts/load_bookshelf_books.py              # Supabaseへ反映
```

Supabase側に `bookshelf_books.sql` を先に一度適用しておく必要がある(SQL Editorで実行)。

## サムネイル画像の追加

1. 対象の本の表紙画像を用意する
2. Supabase Storageの適当なpublicバケット(既存の `usage-guide-media` 等と同様の運用)にアップロードし、公開URLを取得する
3. `bookshelf_books.thumbnail_url` を該当行だけ更新する(Supabase管理画面のTable Editorから直接編集で問題ない)
