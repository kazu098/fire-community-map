-- Rollback for member_auth_read_policies.sql: restore the original public read policies.

alter policy "bookshelf books are publicly readable" on public.bookshelf_books
to anon, authenticated
using (true);

alter policy "bookshelf books history is publicly readable" on public.bookshelf_books_history
to anon, authenticated
using (true);

alter policy "community events are publicly readable" on public.community_events
to anon, authenticated
using (true);

alter policy "community posts are publicly readable" on public.community_posts
to anon, authenticated
using (true);

alter policy "community posts history is publicly readable" on public.community_posts_history
to anon, authenticated
using (true);

alter policy "member availability is publicly readable" on public.member_availability
to anon, authenticated
using (true);

alter policy "member availability overrides are publicly readable" on public.member_availability_overrides
to anon, authenticated
using (true);

alter policy "member links are publicly readable" on public.member_links
to anon, authenticated
using (true);

alter policy "member links history is publicly readable" on public.member_links_history
to anon, authenticated
using (true);

alter policy "member match group members are publicly readable" on public.member_match_group_members
to anon, authenticated
using (true);

alter policy "member match group topics are publicly readable" on public.member_match_group_topics
to anon, authenticated
using (true);

alter policy "member match groups are publicly readable" on public.member_match_groups
to anon, authenticated
using (true);

alter policy "member match schedules are publicly readable" on public.member_match_schedules
to anon, authenticated
using (true);

alter policy "member matching settings are publicly readable" on public.member_matching_settings
to anon, authenticated
using (true);

alter policy "member profile edits are publicly readable" on public.member_profile_edits
to anon, authenticated
using (true);

alter policy "member profiles are publicly readable" on public.member_profiles
to anon, authenticated
using (true);

alter policy "member tags are publicly readable" on public.member_tags
to anon, authenticated
using (true);

alter policy "member tags history is publicly readable" on public.member_tags_history
to anon, authenticated
using (true);

alter policy "topic news cache is publicly readable" on public.topic_news_cache
to anon, authenticated
using (true);

create policy "member locations are publicly readable"
on public.member_locations
for select
to anon
using (map_lat is not null and map_lng is not null);

alter policy "member locations authenticated readable" on public.member_locations
to authenticated
using (true);
