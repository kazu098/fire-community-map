-- Discord OAuth login (GitHub issue #291, phase 4-2): close every remaining
-- anonymous write path, and the one anonymous read RPC that hands out Discord
-- ids. After this, anyone holding only the anon key can neither change nor
-- (together with member_auth_read_policies.sql) read member data.
--
-- !! BREAKING: apply only after
--    * member_auth_policies_profile.sql / _matching.sql / _posts.sql /
--      member_auth_rpc_checks.sql are applied (they add the owner-only
--      `authenticated` policies; without them signed-in members could not
--      write at all), and
--    * the login-required UI (issue #292) is live for everyone.
-- Service-role scripts bypass RLS and are unaffected.
--
-- Rollback: member_auth_close_anon_writes_rollback.sql

-- ---- Drop the legacy open (anon) write policies ----
drop policy if exists "member tags are publicly insertable" on public.member_tags;
drop policy if exists "member tags are publicly updatable" on public.member_tags;
drop policy if exists "member tags are publicly deletable" on public.member_tags;
drop policy if exists "member links are publicly insertable" on public.member_links;
drop policy if exists "member links are publicly deletable" on public.member_links;
drop policy if exists "member profiles self intro is publicly editable" on public.member_profiles;
drop policy if exists "member matching settings are publicly insertable" on public.member_matching_settings;
drop policy if exists "member matching settings are publicly updatable" on public.member_matching_settings;
drop policy if exists "member availability is publicly insertable" on public.member_availability;
drop policy if exists "member availability is publicly deletable" on public.member_availability;
drop policy if exists "member availability overrides are publicly insertable" on public.member_availability_overrides;
drop policy if exists "member availability overrides are publicly deletable" on public.member_availability_overrides;
drop policy if exists "community posts are publicly deletable" on public.community_posts;
drop policy if exists "bookshelf covers are publicly insertable" on storage.objects;

-- ---- RPCs: no anonymous execution ----
revoke execute on function public.update_member_location_map(text, text, text, text, text, double precision, double precision, double precision, double precision, text) from anon;
revoke execute on function public.update_bookshelf_book_thumbnail(uuid, text) from anon;
revoke execute on function public.update_member_profile_publication(text, text, boolean) from anon;

-- The Discord id lookup behind the 「相談してみる」 DM link is for members only.
create or replace function public.get_member_discord_user_id(p_nickname text)
returns text
language sql
security definer
set search_path = public
stable
as $$
  select discord_user_id
  from public.member_profiles
  where nickname = p_nickname
    and public.is_community_member();
$$;

revoke execute on function public.get_member_discord_user_id(text) from anon;
