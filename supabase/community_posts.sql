-- Community posts: stock-style content (books, travel, money/care consultations)
-- curated from specific Discord channels. See design discussion in GitHub issue #59.
-- Applied as a standalone migration, like member_tags_consultation_category.sql,
-- rather than editing schema.sql directly.

create table if not exists public.community_posts (
  id uuid primary key default gen_random_uuid(),
  member_nickname text references public.member_profiles (nickname) on delete set null,
  content_type text not null check (
    content_type in ('book', 'travel', 'money_consultation', 'care_medical')
  ),
  title text,
  summary text not null,
  discord_channel_name text not null,
  discord_message_id text not null unique,
  discord_author_display_name text,
  discord_permalink text not null,
  posted_at timestamptz not null,
  created_at timestamptz not null default now()
);

comment on table public.community_posts is
  'Stock-style content curated from specific Discord channels (books read, travel, money/care consultations). Rows are written only via the service role by scripts/load_community_posts.py; anon can only read/delete (the X button). Does not store Discord user IDs.';

comment on column public.community_posts.discord_message_id is
  'Used to dedupe on re-crawl and to key community_posts_history lookups so deleted posts are not re-added.';

comment on column public.community_posts.member_nickname is
  'Resolved via config/member_discord_name_map.csv. Null when the Discord author could not be matched to a directory member; the post still shows in the community tab but not on any member detail page.';

create index if not exists community_posts_member_nickname_idx
  on public.community_posts (member_nickname);

create index if not exists community_posts_content_type_idx
  on public.community_posts (content_type);

alter table public.community_posts enable row level security;

drop policy if exists "community posts are publicly readable" on public.community_posts;
create policy "community posts are publicly readable"
on public.community_posts
for select
to anon, authenticated
using (true);

drop policy if exists "community posts are publicly deletable" on public.community_posts;
create policy "community posts are publicly deletable"
on public.community_posts
for delete
to anon, authenticated
using (true);

-- No insert/update policies for anon/authenticated: rows are written only via
-- the service role key from scripts/load_community_posts.py. Unlike
-- member_tags/member_links, adding a post is not a user-facing action here.

create table if not exists public.community_posts_history (
  id uuid primary key default gen_random_uuid(),
  discord_message_id text not null,
  action text not null check (action in ('add', 'delete')),
  content_type text not null,
  summary text not null,
  created_at timestamptz not null default now()
);

comment on table public.community_posts_history is
  'Append-only audit trail of community_posts inserts/deletes, written by trigger only. scripts/load_community_posts.py checks this before upserting so a post removed via the X button is not silently re-added on the next crawl.';

create index if not exists community_posts_history_discord_message_id_idx
  on public.community_posts_history (discord_message_id);

alter table public.community_posts_history enable row level security;

drop policy if exists "community posts history is publicly readable" on public.community_posts_history;
create policy "community posts history is publicly readable"
on public.community_posts_history
for select
to anon, authenticated
using (true);

-- No insert/update/delete policies for anon/authenticated: rows are written
-- only by the security-definer trigger function below, which runs as the
-- table owner and therefore bypasses RLS on this table.

create or replace function public.log_community_post_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if TG_OP = 'INSERT' then
    insert into public.community_posts_history (discord_message_id, action, content_type, summary)
    values (new.discord_message_id, 'add', new.content_type, new.summary);
    return new;
  elsif TG_OP = 'DELETE' then
    insert into public.community_posts_history (discord_message_id, action, content_type, summary)
    values (old.discord_message_id, 'delete', old.content_type, old.summary);
    return old;
  end if;
  return null;
end;
$$;

drop trigger if exists log_community_posts_insert on public.community_posts;
create trigger log_community_posts_insert
after insert on public.community_posts
for each row
execute function public.log_community_post_change();

drop trigger if exists log_community_posts_delete on public.community_posts;
create trigger log_community_posts_delete
after delete on public.community_posts
for each row
execute function public.log_community_post_change();

notify pgrst, 'reload schema';
