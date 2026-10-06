-- Public map pins for map/public.html (GitHub issue #253, cut-over to a
-- members-only site).
--
-- map/public.html is an anonymous, public map that shows only where members
-- are (no names). It used to read member_locations directly through the
-- anon-only "member locations are publicly readable" policy, which
-- member_auth_read_policies.sql drops. This view keeps that page working while
-- exposing strictly less than before: only the location columns, never the
-- nickname. Like public_member_profiles, it is owned by postgres and therefore
-- not subject to member_locations' RLS.

create or replace view public.public_member_map_points as
select
  location_text,
  prefecture,
  municipality_optional,
  map_lat,
  map_lng
from public.member_locations
where map_lat is not null
  and map_lng is not null;

comment on view public.public_member_map_points is
  'Location-only pins (no nickname) for the anonymous public map, map/public.html.';

grant select on public.public_member_map_points to anon, authenticated;
