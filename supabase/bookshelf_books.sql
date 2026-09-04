-- Bookshelf tab: FIRE研究所公式本＋メンバー著書を本棚レイアウトで表示するためのテーブル。
-- 既存の member_tags/member_links と同じくオープン編集(anon write可)にはせず、
-- 掲載本の追加・削除は運営(Service Role Key経由のスクリプト)のみが行う想定。

create table if not exists public.bookshelf_books (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('fire_lab', 'member')),
  member_nickname text references public.member_profiles (nickname) on delete set null,
  title text not null,
  author_name text,
  amazon_url text not null,
  thumbnail_url text,
  drive_pdf_url text,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  unique (amazon_url)
);

comment on table public.bookshelf_books is
  '本棚タブに表示する本。source=fire_labはFIRE研究所公式本、source=memberはメンバーが出版した本(member_linksのAmazonリンクから採用)。掲載の追加・削除は運営が管理する非オープン編集テーブル。';

create index if not exists bookshelf_books_source_idx
  on public.bookshelf_books (source, sort_order);

alter table public.bookshelf_books enable row level security;

drop policy if exists "bookshelf books are publicly readable" on public.bookshelf_books;
create policy "bookshelf books are publicly readable"
on public.bookshelf_books
for select
to anon, authenticated
using (true);

notify pgrst, 'reload schema';
