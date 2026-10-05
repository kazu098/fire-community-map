-- Discord OAuth login (GitHub issue #289, phase 3-4): community_posts can be
-- removed only by the member who posted it.
--
-- Deletion was open to anyone (the X button). With Discord login, a signed-in
-- member may remove only their own 本(book) / 旅行(travel) posts -- the two
-- content types that are single-author posts and show the author's name.
-- 相談系 are multi-person threads whose authors are never shown, so they are
-- not removable from the UI. Posts without a resolved member_nickname are not
-- removable either; an operator removes those with the service role.
--
-- The legacy open policy is narrowed to `anon` (signed-out behaviour is
-- unchanged) and dropped later (issue #291). The community_posts_history
-- trigger (so a removed post is not re-added by the next crawl) is unaffected.
--
-- Rollback: see the commented block at the bottom.

alter policy "community posts are publicly deletable" on public.community_posts to anon;

drop policy if exists "community posts are deletable by author" on public.community_posts;
create policy "community posts are deletable by author"
on public.community_posts
for delete
to authenticated
using (
  content_type in ('book', 'travel')
  and member_nickname = public.current_member_nickname()
);

-- ---- Rollback ----
-- drop policy if exists "community posts are deletable by author" on public.community_posts;
-- alter policy "community posts are publicly deletable" on public.community_posts to anon, authenticated;
