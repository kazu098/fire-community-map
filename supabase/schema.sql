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
    category in ('investment_style', 'fire_status', 'mbti', 'skill', 'consultation', 'interest', 'affiliation')
  ),
  value text not null,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  unique (member_nickname, category, value)
);

comment on table public.member_tags is
  'Editable tags shown in the member directory. Open write access by design for the initial rollout (see member_tags_history for an audit trail).';

comment on column public.member_tags.sort_order is
  'Display order within a member+category, user-editable via the directory reorder buttons. Not unique; ties fall back to created_at.';

drop policy if exists "member tags are publicly updatable" on public.member_tags;
create policy "member tags are publicly updatable"
on public.member_tags
for update
to anon, authenticated
using (true)
with check (true);

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
  old_external_self_intro_text text,
  new_external_self_intro_text text,
  edited_at timestamptz not null default now()
);

comment on table public.member_profile_edits is
  'Append-only audit trail of self_intro_text/location_text edits, written by trigger only.';

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
  if new.external_self_intro_text is distinct from old.external_self_intro_text then
    insert into public.member_profile_edits (member_nickname, old_external_self_intro_text, new_external_self_intro_text)
    values (new.nickname, old.external_self_intro_text, new.external_self_intro_text);
  end if;
  if new.location_text is distinct from old.location_text then
    insert into public.member_profile_edits (member_nickname, old_location_text, new_location_text)
    values (new.nickname, old.location_text, new.location_text);
  end if;
  return new;
end;
$$;

drop trigger if exists log_member_profile_edits on public.member_profiles;
create trigger log_member_profile_edits
after update on public.member_profiles
for each row
execute function public.log_member_profile_edit();

-- ================================================================
-- Member directory: open editing of location_text
-- ================================================================
-- Self-reported residence text, editable by anyone (same open-editing
-- pattern as self_intro_text above). Map coordinates are updated through
-- update_member_location_map when the browser can normalize the location.

alter table public.member_profiles add column if not exists location_text text;

comment on column public.member_profiles.location_text is
  'Self-reported residence text, editable by anyone. Synced to member_locations.location_text for map display; map coordinates can be updated through update_member_location_map.';

alter table public.member_profile_edits add column if not exists old_location_text text;
alter table public.member_profile_edits add column if not exists new_location_text text;

grant update (location_text) on public.member_profiles to anon, authenticated;

create or replace function public.sync_member_profile_location_to_map()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.location_text is distinct from old.location_text then
    update public.member_locations
    set location_text = new.location_text
    where nickname = new.nickname
      and new.location_text is not null
      and btrim(new.location_text) <> '';
  end if;
  return new;
end;
$$;

drop trigger if exists sync_member_profile_location_to_map on public.member_profiles;
create trigger sync_member_profile_location_to_map
after update on public.member_profiles
for each row
execute function public.sync_member_profile_location_to_map();

create or replace function public.update_member_location_map(
  p_nickname text,
  p_location_text text,
  p_prefecture text,
  p_municipality_optional text,
  p_location_level text,
  p_lat double precision,
  p_lng double precision,
  p_map_lat double precision,
  p_map_lng double precision,
  p_geocode_source text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_location_text is null or btrim(p_location_text) = '' then
    raise exception 'location_text is required';
  end if;

  if p_location_level not in ('prefecture', 'municipality', 'area', 'region', 'multi_region', 'unknown') then
    raise exception 'invalid location_level: %', p_location_level;
  end if;

  if p_geocode_source not in (
    'prefecture_static',
    'geolonia',
    'manual_alias',
    'manual_review',
    'prefecture_static_fallback',
    'unmatched',
    'empty'
  ) then
    raise exception 'invalid geocode_source: %', p_geocode_source;
  end if;

  if p_lat is null or p_lng is null or p_map_lat is null or p_map_lng is null then
    raise exception 'lat/lng and map_lat/map_lng are required';
  end if;

  update public.member_locations
  set
    location_text = btrim(p_location_text),
    prefecture = nullif(btrim(coalesce(p_prefecture, '')), ''),
    municipality_optional = nullif(btrim(coalesce(p_municipality_optional, '')), ''),
    location_level = p_location_level,
    lat = p_lat,
    lng = p_lng,
    map_lat = p_map_lat,
    map_lng = p_map_lng,
    geocode_source = p_geocode_source
  where nickname = p_nickname;
end;
$$;

revoke execute on function public.update_member_location_map(
  text, text, text, text, text, double precision, double precision, double precision, double precision, text
) from public;

grant execute on function public.update_member_location_map(
  text, text, text, text, text, double precision, double precision, double precision, double precision, text
) to anon, authenticated;

-- ================================================================
-- Member directory: external publication settings
-- ================================================================
-- These flags control only what the external profile directory exposes.
-- The internal member detail page still reads the underlying profile fields.

alter table public.member_profiles add column if not exists nickname_public boolean not null default false;
alter table public.member_profiles add column if not exists avatar_public boolean not null default false;
alter table public.member_profiles add column if not exists external_self_intro_text text;
alter table public.member_profiles add column if not exists self_intro_public boolean not null default false;
alter table public.member_profiles add column if not exists location_public boolean not null default false;
alter table public.member_profiles add column if not exists links_public boolean not null default false;

update public.member_profiles
set external_self_intro_text = self_intro_text
where external_self_intro_text is null
  and self_intro_text is not null;

comment on column public.member_profiles.nickname_public is
  'When true, nickname may be shown on the external public profile directory.';
comment on column public.member_profiles.avatar_public is
  'When true, avatar_url may be shown on the external public profile directory.';
comment on column public.member_profiles.external_self_intro_text is
  'External-facing self-introduction text. Seeded from self_intro_text but edited separately from the internal member profile text.';
comment on column public.member_profiles.self_intro_public is
  'When true, external_self_intro_text may be shown on the external public profile directory.';
comment on column public.member_profiles.location_public is
  'When true, location_text may be shown on the external public profile directory.';
comment on column public.member_profiles.links_public is
  'When true, non-memo member_links may be shown on the external public profile directory.';

grant update (
  nickname_public,
  avatar_public,
  external_self_intro_text,
  self_intro_public,
  location_public,
  links_public
) on public.member_profiles to anon, authenticated;

create or replace function public.prevent_implicit_public_profile_publication()
returns trigger
language plpgsql
as $$
declare
  publication_enable_allowed boolean :=
    coalesce(current_setting('app.allow_public_profile_publication', true), '') = 'on';
begin
  if publication_enable_allowed then
    return new;
  end if;

  if tg_op = 'INSERT' then
    if new.nickname_public
      or new.avatar_public
      or new.self_intro_public
      or new.location_public
      or new.links_public
    then
      raise exception 'External profile publication flags can only be enabled via update_member_profile_publication()'
        using errcode = '42501';
    end if;
    return new;
  end if;

  if (not old.nickname_public and new.nickname_public)
    or (not old.avatar_public and new.avatar_public)
    or (not old.self_intro_public and new.self_intro_public)
    or (not old.location_public and new.location_public)
    or (not old.links_public and new.links_public)
  then
    raise exception 'External profile publication flags can only be enabled via update_member_profile_publication()'
      using errcode = '42501';
  end if;

  return new;
end;
$$;

drop trigger if exists prevent_implicit_public_profile_publication on public.member_profiles;
create trigger prevent_implicit_public_profile_publication
before insert or update on public.member_profiles
for each row
execute function public.prevent_implicit_public_profile_publication();

create or replace function public.update_member_profile_publication(
  target_nickname text,
  field_name text,
  enabled boolean
)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  updated_count integer;
begin
  if field_name not in (
    'nickname_public',
    'avatar_public',
    'self_intro_public',
    'location_public',
    'links_public'
  ) then
    raise exception 'Invalid member profile publication field: %', field_name
      using errcode = '22023';
  end if;

  perform set_config('app.allow_public_profile_publication', 'on', true);

  execute format(
    'update public.member_profiles set %I = $1 where nickname = $2',
    field_name
  )
  using enabled, target_nickname;

  get diagnostics updated_count = row_count;
  if updated_count = 0 then
    raise exception 'Member profile not found: %', target_nickname
      using errcode = '02000';
  end if;
end;
$$;

revoke all on function public.update_member_profile_publication(text, text, boolean) from public;
grant execute on function public.update_member_profile_publication(text, text, boolean) to anon, authenticated;

create table if not exists public.member_profile_publication_edits (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null,
  field_name text not null check (
    field_name in ('nickname_public', 'avatar_public', 'self_intro_public', 'location_public', 'links_public')
  ),
  old_value boolean,
  new_value boolean,
  edited_at timestamptz not null default now()
);

comment on table public.member_profile_publication_edits is
  'Append-only audit trail of external publication setting changes, written by trigger only.';

create index if not exists member_profile_publication_edits_member_nickname_idx
  on public.member_profile_publication_edits (member_nickname);

alter table public.member_profile_publication_edits enable row level security;

drop policy if exists "member profile publication edits are publicly readable" on public.member_profile_publication_edits;
-- No select/insert/update/delete policies for anon/authenticated. Publication
-- edit history contains member_nickname even when nickname_public is false, so
-- it must be reviewed with the service role only.

create or replace function public.log_member_profile_publication_edit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.nickname_public is distinct from old.nickname_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'nickname_public', old.nickname_public, new.nickname_public);
  end if;
  if new.avatar_public is distinct from old.avatar_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'avatar_public', old.avatar_public, new.avatar_public);
  end if;
  if new.self_intro_public is distinct from old.self_intro_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'self_intro_public', old.self_intro_public, new.self_intro_public);
  end if;
  if new.location_public is distinct from old.location_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'location_public', old.location_public, new.location_public);
  end if;
  if new.links_public is distinct from old.links_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'links_public', old.links_public, new.links_public);
  end if;
  return new;
end;
$$;

drop trigger if exists log_member_profile_publication_edits on public.member_profiles;
create trigger log_member_profile_publication_edits
after update on public.member_profiles
for each row
execute function public.log_member_profile_publication_edit();

create or replace view public.public_member_profiles as
select
  p.id as member_id,
  case when p.nickname_public then p.nickname else null end as display_nickname,
  case when p.avatar_public then p.avatar_url else null end as display_avatar_url,
  case when p.self_intro_public then p.external_self_intro_text else null end as display_self_intro_text,
  case when p.location_public then p.location_text else null end as display_location_text,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'category', t.category,
          'value', t.value,
          'sort_order', t.sort_order
        )
        order by t.category, t.sort_order, t.created_at
      )
      from public.member_tags t
      where t.member_nickname = p.nickname
        and t.category <> 'affiliation'
    ),
    '[]'::jsonb
  ) as tags,
  case
    when p.links_public then coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'label', l.label,
            'url', l.url
          )
          order by l.created_at
        )
        from public.member_links l
        where l.member_nickname = p.nickname
          and l.label <> '個人メモ'
      ),
      '[]'::jsonb
    )
    else '[]'::jsonb
  end as links
from public.member_profiles p;

comment on view public.public_member_profiles is
  'External public profile directory. Non-public fields are nulled and personal memo links are always excluded.';

grant select on public.public_member_profiles to anon, authenticated;
