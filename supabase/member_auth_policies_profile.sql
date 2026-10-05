-- Discord OAuth login (GitHub issue #286, phase 3-1): per-member write
-- policies for member_tags, member_links and member_profiles.
--
-- Until now these tables accepted writes from anyone holding the anon key
-- ("to anon, authenticated using (true)"). Postgres combines permissive
-- policies with OR, so simply adding an owner-only policy next to a policy
-- that also covers `authenticated` would restrict nobody. Instead:
--   1. the legacy open policies are narrowed to `anon` only, so signed-out
--      visitors keep working exactly as before (backward compatible);
--   2. new owner-only policies apply to `authenticated`, i.e. anyone signed
--      in with Discord can only write rows of their own member
--      (current_member_nickname(), see member_auth.sql).
-- The legacy anon policies are dropped later in the "close anon writes" step
-- (issue #291). Service-role scripts bypass RLS and are unaffected.
--
-- Rollback: see the commented block at the bottom.

-- ---- member_tags ----
alter policy "member tags are publicly insertable" on public.member_tags to anon;
alter policy "member tags are publicly updatable" on public.member_tags to anon;
alter policy "member tags are publicly deletable" on public.member_tags to anon;

drop policy if exists "member tags are insertable by owner" on public.member_tags;
create policy "member tags are insertable by owner"
on public.member_tags
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member tags are updatable by owner" on public.member_tags;
create policy "member tags are updatable by owner"
on public.member_tags
for update
to authenticated
using (member_nickname = public.current_member_nickname())
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member tags are deletable by owner" on public.member_tags;
create policy "member tags are deletable by owner"
on public.member_tags
for delete
to authenticated
using (member_nickname = public.current_member_nickname());

-- ---- member_links ----
alter policy "member links are publicly insertable" on public.member_links to anon;
alter policy "member links are publicly deletable" on public.member_links to anon;

drop policy if exists "member links are insertable by owner" on public.member_links;
create policy "member links are insertable by owner"
on public.member_links
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member links are deletable by owner" on public.member_links;
create policy "member links are deletable by owner"
on public.member_links
for delete
to authenticated
using (member_nickname = public.current_member_nickname());

-- ---- member_profiles (column-level UPDATE grants are unchanged) ----
alter policy "member profiles self intro is publicly editable" on public.member_profiles to anon;

drop policy if exists "member profiles are updatable by owner" on public.member_profiles;
create policy "member profiles are updatable by owner"
on public.member_profiles
for update
to authenticated
using (nickname = public.current_member_nickname())
with check (nickname = public.current_member_nickname());

-- ---- Rollback ----
-- drop policy if exists "member tags are insertable by owner" on public.member_tags;
-- drop policy if exists "member tags are updatable by owner" on public.member_tags;
-- drop policy if exists "member tags are deletable by owner" on public.member_tags;
-- drop policy if exists "member links are insertable by owner" on public.member_links;
-- drop policy if exists "member links are deletable by owner" on public.member_links;
-- drop policy if exists "member profiles are updatable by owner" on public.member_profiles;
-- alter policy "member tags are publicly insertable" on public.member_tags to anon, authenticated;
-- alter policy "member tags are publicly updatable" on public.member_tags to anon, authenticated;
-- alter policy "member tags are publicly deletable" on public.member_tags to anon, authenticated;
-- alter policy "member links are publicly insertable" on public.member_links to anon, authenticated;
-- alter policy "member links are publicly deletable" on public.member_links to anon, authenticated;
-- alter policy "member profiles self intro is publicly editable" on public.member_profiles to anon, authenticated;
