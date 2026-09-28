-- member_profiles.discord_user_id previously inherited the same public
-- SELECT grant as the rest of the table (RLS policies only restrict rows,
-- not columns), so anyone with the anon key could bulk-download the full
-- nickname <-> Discord user id mapping for every member in a single
-- request, instead of only being able to look up one member's DM link at a
-- time from their profile page as the "相談してみる" feature intends.
--
-- This revokes that column's SELECT grant and replaces the bulk read with a
-- single-row RPC lookup, so the client can still show the DM link for one
-- member at a time without exposing the whole mapping.

-- Column-level REVOKE alone does not narrow an existing table-wide SELECT
-- grant (they are separate, additive privilege entries in Postgres), so this
-- has to revoke SELECT entirely and re-grant every other column explicitly --
-- the same revoke-then-grant-columns pattern already used for UPDATE
-- elsewhere in this schema (see member_matching.sql).
revoke select on public.member_profiles from anon, authenticated;

grant select (
  id,
  nickname,
  avatar_url,
  self_intro_text,
  self_intro_url,
  self_intro_posted_at,
  created_at,
  updated_at,
  location_text,
  nickname_public,
  avatar_public,
  self_intro_public,
  location_public,
  links_public,
  external_self_intro_text
) on public.member_profiles to anon, authenticated;

create or replace function public.get_member_discord_user_id(p_nickname text)
returns text
language sql
security definer
set search_path = public
stable
as $$
  select discord_user_id
  from public.member_profiles
  where nickname = p_nickname;
$$;

revoke execute on function public.get_member_discord_user_id(text) from public;

grant execute on function public.get_member_discord_user_id(text) to anon, authenticated;
