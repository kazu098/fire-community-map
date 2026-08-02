-- Allow the browser to update map coordinates only when a member edits
-- their self-reported residence from the member detail screen.

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

