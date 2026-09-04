-- Allow members to upload/replace a book's thumbnail image from the browser.
-- Apply this once after bookshelf_books.sql.
--
-- bookshelf_books stays read-only for anon (see bookshelf_books.sql); this adds
-- a narrowly-scoped RPC that can only touch thumbnail_url, plus a public Storage
-- bucket for the uploaded images and an audit trail (same open-edit + history
-- pattern as member_tags/member_links).

-- ---- Storage bucket for uploaded cover images ----

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('bookshelf-covers', 'bookshelf-covers', true, 5242880, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "bookshelf covers are publicly insertable" on storage.objects;
create policy "bookshelf covers are publicly insertable"
on storage.objects
for insert
to anon, authenticated
with check (bucket_id = 'bookshelf-covers');

-- ---- Audit trail ----

create table if not exists public.bookshelf_books_history (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null,
  member_nickname text,
  old_thumbnail_url text,
  new_thumbnail_url text,
  created_at timestamptz not null default now()
);

comment on table public.bookshelf_books_history is
  'Append-only audit trail of bookshelf_books.thumbnail_url changes made via update_bookshelf_book_thumbnail(), so open self-service uploads can be reviewed/reverted.';

alter table public.bookshelf_books_history enable row level security;

drop policy if exists "bookshelf books history is publicly readable" on public.bookshelf_books_history;
create policy "bookshelf books history is publicly readable"
on public.bookshelf_books_history
for select
to anon, authenticated
using (true);

-- ---- Scoped RPC: can only change thumbnail_url of an existing row ----

create or replace function public.update_bookshelf_book_thumbnail(
  p_id uuid,
  p_thumbnail_url text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_old text;
  v_nickname text;
begin
  if p_thumbnail_url is null or btrim(p_thumbnail_url) = '' then
    raise exception 'thumbnail_url is required';
  end if;

  select thumbnail_url, member_nickname into v_old, v_nickname
  from public.bookshelf_books
  where id = p_id;

  if not found then
    raise exception 'book not found: %', p_id;
  end if;

  update public.bookshelf_books
  set thumbnail_url = p_thumbnail_url
  where id = p_id;

  insert into public.bookshelf_books_history (book_id, member_nickname, old_thumbnail_url, new_thumbnail_url)
  values (p_id, v_nickname, v_old, p_thumbnail_url);
end;
$$;

revoke execute on function public.update_bookshelf_book_thumbnail(uuid, text) from public;
grant execute on function public.update_bookshelf_book_thumbnail(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
