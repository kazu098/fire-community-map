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
