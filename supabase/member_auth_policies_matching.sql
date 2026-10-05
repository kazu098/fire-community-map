-- Discord OAuth login (GitHub issue #287, phase 3-2): per-member write
-- policies for the ゆるマッチング tables (member_matching_settings,
-- member_availability, member_availability_overrides).
--
-- Same approach as member_auth_policies_profile.sql: the legacy open policies
-- are narrowed to `anon` (signed-out behaviour is unchanged) and new
-- owner-only policies apply to `authenticated`. The legacy anon policies are
-- dropped later (issue #291). The matching batch scripts use the service role
-- and bypass RLS.
--
-- member_matching_settings is written by PostgREST upsert
-- (INSERT ... ON CONFLICT DO UPDATE), which needs both the insert and the
-- update policy to pass for the same row. Column-level UPDATE grants are
-- unchanged (see member_matching.sql).
--
-- Rollback: see the commented block at the bottom.

-- ---- member_matching_settings ----
alter policy "member matching settings are publicly insertable" on public.member_matching_settings to anon;
alter policy "member matching settings are publicly updatable" on public.member_matching_settings to anon;

drop policy if exists "member matching settings are insertable by owner" on public.member_matching_settings;
create policy "member matching settings are insertable by owner"
on public.member_matching_settings
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member matching settings are updatable by owner" on public.member_matching_settings;
create policy "member matching settings are updatable by owner"
on public.member_matching_settings
for update
to authenticated
using (member_nickname = public.current_member_nickname())
with check (member_nickname = public.current_member_nickname());

-- ---- member_availability ----
alter policy "member availability is publicly insertable" on public.member_availability to anon;
alter policy "member availability is publicly deletable" on public.member_availability to anon;

drop policy if exists "member availability is insertable by owner" on public.member_availability;
create policy "member availability is insertable by owner"
on public.member_availability
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member availability is deletable by owner" on public.member_availability;
create policy "member availability is deletable by owner"
on public.member_availability
for delete
to authenticated
using (member_nickname = public.current_member_nickname());

-- ---- member_availability_overrides ----
alter policy "member availability overrides are publicly insertable" on public.member_availability_overrides to anon;
alter policy "member availability overrides are publicly deletable" on public.member_availability_overrides to anon;

drop policy if exists "member availability overrides are insertable by owner" on public.member_availability_overrides;
create policy "member availability overrides are insertable by owner"
on public.member_availability_overrides
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "member availability overrides are deletable by owner" on public.member_availability_overrides;
create policy "member availability overrides are deletable by owner"
on public.member_availability_overrides
for delete
to authenticated
using (member_nickname = public.current_member_nickname());

-- ---- Rollback ----
-- drop policy if exists "member matching settings are insertable by owner" on public.member_matching_settings;
-- drop policy if exists "member matching settings are updatable by owner" on public.member_matching_settings;
-- drop policy if exists "member availability is insertable by owner" on public.member_availability;
-- drop policy if exists "member availability is deletable by owner" on public.member_availability;
-- drop policy if exists "member availability overrides are insertable by owner" on public.member_availability_overrides;
-- drop policy if exists "member availability overrides are deletable by owner" on public.member_availability_overrides;
-- alter policy "member matching settings are publicly insertable" on public.member_matching_settings to anon, authenticated;
-- alter policy "member matching settings are publicly updatable" on public.member_matching_settings to anon, authenticated;
-- alter policy "member availability is publicly insertable" on public.member_availability to anon, authenticated;
-- alter policy "member availability is publicly deletable" on public.member_availability to anon, authenticated;
-- alter policy "member availability overrides are publicly insertable" on public.member_availability_overrides to anon, authenticated;
-- alter policy "member availability overrides are publicly deletable" on public.member_availability_overrides to anon, authenticated;
