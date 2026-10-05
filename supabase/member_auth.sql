-- Discord OAuth login foundation (GitHub issue #253, phase 1).
--
-- Maps the signed-in Supabase Auth user (Discord provider) to the community
-- member they are, via auth.identities.provider_id (= Discord user id) ==
-- member_profiles.discord_user_id. Later phases rewrite every RLS policy to
-- depend on current_member_nickname() instead of "anyone with the anon key".
--
-- This migration changes no existing behaviour: no policy is touched, and
-- until someone signs in with Discord the function simply returns null.
-- Plan: docs/discord-oauth-login-plan.md

-- One Discord account must resolve to exactly one member. There are no
-- duplicates today; the index keeps it that way (nulls are not indexed).
create unique index if not exists member_profiles_discord_user_id_key
  on public.member_profiles (discord_user_id)
  where discord_user_id is not null;

-- Supabase grants EXECUTE on new public functions to anon by default, which
-- `from public` alone does not remove, so anon is revoked explicitly.

-- Nickname of the member the current session belongs to, or null when the
-- caller is not signed in with Discord or their Discord account is not
-- linked to any member_profiles row.
create or replace function public.current_member_nickname()
returns text
language sql
security definer
set search_path = public
stable
as $$
  select mp.nickname
  from auth.identities i
  join public.member_profiles mp on mp.discord_user_id = i.provider_id
  where i.user_id = auth.uid()
    and i.provider = 'discord'
  limit 1;
$$;

comment on function public.current_member_nickname() is
  'Nickname of the member linked to the signed-in Discord account (auth.identities.provider_id = member_profiles.discord_user_id); null if not signed in or not a known member. RLS policies key off this.';

revoke execute on function public.current_member_nickname() from public, anon;

grant execute on function public.current_member_nickname() to authenticated;

-- True only for a signed-in user who is a known community member. Used by the
-- read policies once the site is members-only (phase 4).
create or replace function public.is_community_member()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select public.current_member_nickname() is not null;
$$;

revoke execute on function public.is_community_member() from public, anon;

grant execute on function public.is_community_member() to authenticated;
