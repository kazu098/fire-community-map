-- Discord OAuth login (GitHub issue #290, phase 4-1): the site becomes
-- members-only. Every "publicly readable" SELECT policy is narrowed from
-- `anon, authenticated using (true)` to signed-in community members only
-- (is_community_member(), see member_auth.sql). Anyone holding just the anon
-- key -- which is embedded in index.html -- can no longer read member data.
--
-- !! BREAKING: apply only once the Discord login UI is live for everyone
-- (login required by default, issue #292) and every member's discord_user_id
-- is linked (100% as of 2026-10-06). Applying it earlier locks signed-out
-- visitors out of the whole site.
--
-- Kept open on purpose:
--   * public.public_member_profiles (view, owned by postgres, bypasses RLS):
--     the publicly-flagged subset read anonymously by public.html /
--     public-embed.html (WordPress embed).
--   * Storage buckets are public: avatar / travel photo / usage-guide URLs
--     can still be fetched by anyone who knows the URL. Not changed here.
--   * member_profile_publication_edits has no SELECT policy (nobody reads it
--     through the API) and stays that way.
--   * member_profiles' column-level SELECT grants (discord_user_id hidden)
--     are unchanged.
--
-- `(select ...)` makes Postgres evaluate the check once per statement instead
-- of once per row. Service-role scripts bypass RLS and are unaffected.
--
-- Rollback: member_auth_read_policies_rollback.sql

alter policy "bookshelf books are publicly readable" on public.bookshelf_books
to authenticated
using ((select public.is_community_member()));

alter policy "bookshelf books history is publicly readable" on public.bookshelf_books_history
to authenticated
using ((select public.is_community_member()));

alter policy "community events are publicly readable" on public.community_events
to authenticated
using ((select public.is_community_member()));

alter policy "community posts are publicly readable" on public.community_posts
to authenticated
using ((select public.is_community_member()));

alter policy "community posts history is publicly readable" on public.community_posts_history
to authenticated
using ((select public.is_community_member()));

alter policy "member availability is publicly readable" on public.member_availability
to authenticated
using ((select public.is_community_member()));

alter policy "member availability overrides are publicly readable" on public.member_availability_overrides
to authenticated
using ((select public.is_community_member()));

alter policy "member links are publicly readable" on public.member_links
to authenticated
using ((select public.is_community_member()));

alter policy "member links history is publicly readable" on public.member_links_history
to authenticated
using ((select public.is_community_member()));

alter policy "member match group members are publicly readable" on public.member_match_group_members
to authenticated
using ((select public.is_community_member()));

alter policy "member match group topics are publicly readable" on public.member_match_group_topics
to authenticated
using ((select public.is_community_member()));

alter policy "member match groups are publicly readable" on public.member_match_groups
to authenticated
using ((select public.is_community_member()));

alter policy "member match schedules are publicly readable" on public.member_match_schedules
to authenticated
using ((select public.is_community_member()));

alter policy "member matching settings are publicly readable" on public.member_matching_settings
to authenticated
using ((select public.is_community_member()));

alter policy "member profile edits are publicly readable" on public.member_profile_edits
to authenticated
using ((select public.is_community_member()));

alter policy "member profiles are publicly readable" on public.member_profiles
to authenticated
using ((select public.is_community_member()));

alter policy "member tags are publicly readable" on public.member_tags
to authenticated
using ((select public.is_community_member()));

alter policy "member tags history is publicly readable" on public.member_tags_history
to authenticated
using ((select public.is_community_member()));

alter policy "topic news cache is publicly readable" on public.topic_news_cache
to authenticated
using ((select public.is_community_member()));

-- member_locations has an anon-only policy (rows with map coordinates) and an
-- authenticated policy; the anon one goes away.
drop policy if exists "member locations are publicly readable" on public.member_locations;
alter policy "member locations authenticated readable" on public.member_locations
to authenticated
using ((select public.is_community_member()));
