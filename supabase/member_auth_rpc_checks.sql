-- Discord OAuth login (GitHub issue #288, phase 3-3): ownership checks for
-- the writes that do not go through plain RLS policies.
--
-- * update_member_location_map (SECURITY DEFINER, writes member_locations):
--   a signed-in caller may only update their own member's location.
-- * update_bookshelf_book_thumbnail (SECURITY DEFINER) and the
--   bookshelf-covers storage upload: a signed-in caller must be a known
--   community member.
-- * update_member_profile_publication is SECURITY INVOKER, so it is already
--   limited to the caller's own row by the member_profiles update policy in
--   member_auth_policies_profile.sql; no change needed here.
--
-- Compatibility: while signed-out access is still allowed (until issue #291),
-- a call with no Supabase Auth user (auth.uid() is null: anon key or service
-- role) behaves exactly as before. Once #291 revokes the anon grants, only the
-- signed-in path remains.
--
-- Rollback: re-apply the original definitions from schema.sql /
-- bookshelf_books_thumbnail_upload.sql, and see the commented block at the bottom.

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
declare
  profile_exists boolean;
begin
  if auth.uid() is not null and p_nickname is distinct from public.current_member_nickname() then
    raise exception 'You can only update your own location'
      using errcode = '42501';
  end if;

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

  select exists (
    select 1
    from public.member_profiles
    where nickname = p_nickname
  ) into profile_exists;

  if not profile_exists then
    raise exception 'Member profile not found: %', p_nickname;
  end if;

  insert into public.member_locations (
    nickname,
    location_text,
    prefecture,
    municipality_optional,
    location_level,
    lat,
    lng,
    map_lat,
    map_lng,
    geocode_source
  )
  values (
    p_nickname,
    btrim(p_location_text),
    nullif(btrim(coalesce(p_prefecture, '')), ''),
    nullif(btrim(coalesce(p_municipality_optional, '')), ''),
    p_location_level,
    p_lat,
    p_lng,
    p_map_lat,
    p_map_lng,
    p_geocode_source
  )
  on conflict (nickname) do update
  set
    location_text = excluded.location_text,
    prefecture = excluded.prefecture,
    municipality_optional = excluded.municipality_optional,
    location_level = excluded.location_level,
    lat = excluded.lat,
    lng = excluded.lng,
    map_lat = excluded.map_lat,
    map_lng = excluded.map_lng,
    geocode_source = excluded.geocode_source;
end;
$$;

create or replace function public.update_bookshelf_book_thumbnail(p_id uuid, p_thumbnail_url text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_old text;
  v_nickname text;
begin
  if auth.uid() is not null and not public.is_community_member() then
    raise exception 'Only community members can update book thumbnails'
      using errcode = '42501';
  end if;

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

-- bookshelf-covers uploads: signed-in callers must be community members.
alter policy "bookshelf covers are publicly insertable" on storage.objects to anon;

drop policy if exists "bookshelf covers are insertable by members" on storage.objects;
create policy "bookshelf covers are insertable by members"
on storage.objects
for insert
to authenticated
with check (bucket_id = 'bookshelf-covers' and public.is_community_member());

-- ---- Rollback (policy part) ----
-- drop policy if exists "bookshelf covers are insertable by members" on storage.objects;
-- alter policy "bookshelf covers are publicly insertable" on storage.objects to anon, authenticated;
