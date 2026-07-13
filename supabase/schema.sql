-- Supabase schema for the member location map.
-- Apply this in the Supabase SQL editor or via a migration.

create extension if not exists pgcrypto;

create table if not exists public.member_locations (
  id uuid primary key default gen_random_uuid(),
  nickname text not null,
  location_text text not null,
  prefecture text,
  municipality_optional text,
  location_level text not null check (
    location_level in ('prefecture', 'municipality', 'area', 'region', 'multi_region', 'unknown')
  ),
  lat double precision,
  lng double precision,
  map_lat double precision,
  map_lng double precision,
  geocode_source text not null check (
    geocode_source in (
      'prefecture_static',
      'geolonia',
      'manual_alias',
      'manual_review',
      'prefecture_static_fallback',
      'unmatched',
      'empty'
    )
  ),
  avatar_path text,
  avatar_hash text,
  imported_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint member_locations_lat_lng_pair check (
    (lat is null and lng is null) or (lat is not null and lng is not null)
  ),
  constraint member_locations_map_lat_lng_pair check (
    (map_lat is null and map_lng is null) or (map_lat is not null and map_lng is not null)
  )
);

comment on table public.member_locations is
  'Display-only member location records for the community map. Does not store Discord user IDs.';
comment on column public.member_locations.location_text is
  'Original Google Form free-text location input.';
comment on column public.member_locations.lat is
  'Canonical representative latitude for the normalized location.';
comment on column public.member_locations.lng is
  'Canonical representative longitude for the normalized location.';
comment on column public.member_locations.map_lat is
  'Display latitude for Leaflet markers. May be offset from lat to avoid marker stacking.';
comment on column public.member_locations.map_lng is
  'Display longitude for Leaflet markers. May be offset from lng to avoid marker stacking.';
comment on column public.member_locations.avatar_path is
  'Supabase Storage object path under the member-avatars bucket.';

create index if not exists member_locations_prefecture_idx
  on public.member_locations (prefecture);

create index if not exists member_locations_location_level_idx
  on public.member_locations (location_level);

create index if not exists member_locations_map_point_idx
  on public.member_locations (map_lat, map_lng)
  where map_lat is not null and map_lng is not null;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_member_locations_updated_at on public.member_locations;
create trigger set_member_locations_updated_at
before update on public.member_locations
for each row
execute function public.set_updated_at();

alter table public.member_locations enable row level security;

drop policy if exists "member locations are publicly readable" on public.member_locations;
create policy "member locations are publicly readable"
on public.member_locations
for select
to anon
using (
  map_lat is not null
  and map_lng is not null
);

drop policy if exists "member locations authenticated readable" on public.member_locations;
create policy "member locations authenticated readable"
on public.member_locations
for select
to authenticated
using (true);

-- No insert/update/delete policies are defined for anon or authenticated roles.
-- Writes must use the Supabase service role key from a trusted server-side script.

-- Storage setup:
-- Create a public bucket named `member-avatars` in Supabase Storage.
-- Store only copied Discord avatar images there, not Discord user IDs.
-- Example object path: member-avatars/{member_location_id}.png

-- ================================================================
-- Member directory: profiles + tags
-- ================================================================
-- Tags are sourced from self-reported member profile data (Google Form /
-- spreadsheet) and Discord self-introduction posts. Editing is intentionally
-- open (no per-member auth) for the initial rollout; every add/delete is
-- logged to member_tags_history so changes can be audited and reverted by
-- hand if needed.

create table if not exists public.member_profiles (
  id uuid primary key default gen_random_uuid(),
  nickname text not null unique,
  avatar_url text,
  self_intro_text text,
  self_intro_url text,
  self_intro_posted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.member_profiles is
  'Member directory profile data sourced from the member spreadsheet and Discord self-introduction channel. Does not store Discord user IDs.';
comment on column public.member_profiles.self_intro_url is
  'Permalink to the original Discord self-introduction message (discord.com/channels/...).';

drop trigger if exists set_member_profiles_updated_at on public.member_profiles;
create trigger set_member_profiles_updated_at
before update on public.member_profiles
for each row
execute function public.set_updated_at();

alter table public.member_profiles enable row level security;

drop policy if exists "member profiles are publicly readable" on public.member_profiles;
create policy "member profiles are publicly readable"
on public.member_profiles
for select
to anon, authenticated
using (true);

-- No insert/update/delete policies for anon/authenticated: profile rows are
-- seeded/updated via the Supabase service role key from scripts/load_member_profiles.py.

create table if not exists public.member_tags (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on delete cascade,
  category text not null check (
    category in ('investment_style', 'fire_status', 'mbti', 'skill', 'interest')
  ),
  value text not null,
  created_at timestamptz not null default now(),
  unique (member_nickname, category, value)
);

comment on table public.member_tags is
  'Editable tags shown in the member directory. Open write access by design for the initial rollout (see member_tags_history for an audit trail).';

create index if not exists member_tags_member_nickname_idx
  on public.member_tags (member_nickname);

alter table public.member_tags enable row level security;

drop policy if exists "member tags are publicly readable" on public.member_tags;
create policy "member tags are publicly readable"
on public.member_tags
for select
to anon, authenticated
using (true);

drop policy if exists "member tags are publicly insertable" on public.member_tags;
create policy "member tags are publicly insertable"
on public.member_tags
for insert
to anon, authenticated
with check (true);

drop policy if exists "member tags are publicly deletable" on public.member_tags;
create policy "member tags are publicly deletable"
on public.member_tags
for delete
to anon, authenticated
using (true);

create table if not exists public.member_tags_history (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null,
  action text not null check (action in ('add', 'delete')),
  category text not null,
  value text not null,
  created_at timestamptz not null default now()
);

comment on table public.member_tags_history is
  'Append-only audit trail of member_tags inserts/deletes, written by trigger only. Lets an open-editing tag list be reviewed/reverted by hand.';

create index if not exists member_tags_history_member_nickname_idx
  on public.member_tags_history (member_nickname);

alter table public.member_tags_history enable row level security;

drop policy if exists "member tags history is publicly readable" on public.member_tags_history;
create policy "member tags history is publicly readable"
on public.member_tags_history
for select
to anon, authenticated
using (true);

-- No insert/update/delete policies for anon/authenticated: rows are written
-- only by the security-definer trigger function below, which runs as the
-- table owner and therefore bypasses RLS on this table.

create or replace function public.log_member_tag_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if TG_OP = 'INSERT' then
    insert into public.member_tags_history (member_nickname, action, category, value)
    values (new.member_nickname, 'add', new.category, new.value);
    return new;
  elsif TG_OP = 'DELETE' then
    insert into public.member_tags_history (member_nickname, action, category, value)
    values (old.member_nickname, 'delete', old.category, old.value);
    return old;
  end if;
  return null;
end;
$$;

drop trigger if exists log_member_tags_insert on public.member_tags;
create trigger log_member_tags_insert
after insert on public.member_tags
for each row
execute function public.log_member_tag_change();

drop trigger if exists log_member_tags_delete on public.member_tags;
create trigger log_member_tags_delete
after delete on public.member_tags
for each row
execute function public.log_member_tag_change();

-- ================================================================
-- Member directory: external links (note / YouTube / blog etc.)
-- ================================================================
-- Same open-editing + audit-trail pattern as member_tags above.

create table if not exists public.member_links (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on delete cascade,
  label text not null,
  url text not null,
  created_at timestamptz not null default now(),
  unique (member_nickname, url)
);

comment on table public.member_links is
  'Member-submitted links (note, YouTube, blog, etc.) shown in the member directory. Open write access by design, same as member_tags.';

create index if not exists member_links_member_nickname_idx
  on public.member_links (member_nickname);

alter table public.member_links enable row level security;

drop policy if exists "member links are publicly readable" on public.member_links;
create policy "member links are publicly readable"
on public.member_links
for select
to anon, authenticated
using (true);

drop policy if exists "member links are publicly insertable" on public.member_links;
create policy "member links are publicly insertable"
on public.member_links
for insert
to anon, authenticated
with check (true);

drop policy if exists "member links are publicly deletable" on public.member_links;
create policy "member links are publicly deletable"
on public.member_links
for delete
to anon, authenticated
using (true);

create table if not exists public.member_links_history (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null,
  action text not null check (action in ('add', 'delete')),
  label text not null,
  url text not null,
  created_at timestamptz not null default now()
);

comment on table public.member_links_history is
  'Append-only audit trail of member_links inserts/deletes, written by trigger only.';

alter table public.member_links_history enable row level security;

drop policy if exists "member links history is publicly readable" on public.member_links_history;
create policy "member links history is publicly readable"
on public.member_links_history
for select
to anon, authenticated
using (true);

create or replace function public.log_member_link_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if TG_OP = 'INSERT' then
    insert into public.member_links_history (member_nickname, action, label, url)
    values (new.member_nickname, 'add', new.label, new.url);
    return new;
  elsif TG_OP = 'DELETE' then
    insert into public.member_links_history (member_nickname, action, label, url)
    values (old.member_nickname, 'delete', old.label, old.url);
    return old;
  end if;
  return null;
end;
$$;

drop trigger if exists log_member_links_insert on public.member_links;
create trigger log_member_links_insert
after insert on public.member_links
for each row
execute function public.log_member_link_change();

drop trigger if exists log_member_links_delete on public.member_links;
create trigger log_member_links_delete
after delete on public.member_links
for each row
execute function public.log_member_link_change();

alter table public.member_profiles drop column if exists external_links;

-- ================================================================
-- Member directory: open editing of self_intro_text
-- ================================================================
-- Members can add/edit their own self-introduction text if it's missing or
-- outdated. Restricted to just this column (not nickname/avatar_url/etc.) via
-- column-level GRANT, on top of the same open-editing RLS pattern used above.

revoke update on public.member_profiles from anon, authenticated;
grant update (self_intro_text) on public.member_profiles to anon, authenticated;

drop policy if exists "member profiles self intro is publicly editable" on public.member_profiles;
create policy "member profiles self intro is publicly editable"
on public.member_profiles
for update
to anon, authenticated
using (true)
with check (true);

create table if not exists public.member_profile_edits (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null,
  old_self_intro_text text,
  new_self_intro_text text,
  edited_at timestamptz not null default now()
);

comment on table public.member_profile_edits is
  'Append-only audit trail of self_intro_text edits, written by trigger only.';

alter table public.member_profile_edits enable row level security;

drop policy if exists "member profile edits are publicly readable" on public.member_profile_edits;
create policy "member profile edits are publicly readable"
on public.member_profile_edits
for select
to anon, authenticated
using (true);

create or replace function public.log_member_profile_edit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.self_intro_text is distinct from old.self_intro_text then
    insert into public.member_profile_edits (member_nickname, old_self_intro_text, new_self_intro_text)
    values (new.nickname, old.self_intro_text, new.self_intro_text);
  end if;
  return new;
end;
$$;

drop trigger if exists log_member_profile_edits on public.member_profiles;
create trigger log_member_profile_edits
after update on public.member_profiles
for each row
execute function public.log_member_profile_edit();
