-- Allow the browser to update map coordinates only when a member edits
-- their self-reported residence from the member detail screen.

create unique index if not exists member_locations_nickname_key
  on public.member_locations (nickname);

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

revoke execute on function public.update_member_location_map(
  text, text, text, text, text, double precision, double precision, double precision, double precision, text
) from public;

grant execute on function public.update_member_location_map(
  text, text, text, text, text, double precision, double precision, double precision, double precision, text
) to anon, authenticated;
