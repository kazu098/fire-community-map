-- F研の入会時期 (GitHub issue #324): the month a member joined, shown on their profile as
-- 「2025年4月入会」 and used by the ゆるマッチング mentor-style grouping (issue #325).
--
-- Filled by scripts/sync_member_joined_month.py (service role, weekly) from the month of the
-- member's FIRST post in the Discord self-intro channel (joined_month_source = 'self_intro').
-- Members without a self-intro have none until they pick one themselves on the map; once a
-- member sets it (joined_month_source = 'member') the sync never overwrites it.
--
-- The row-level "updatable by owner" policy (member_auth_policies_profile.sql) already limits
-- authenticated updates to the member's own row; this only adds the column-level grants.
-- member_profiles uses column-level SELECT grants (discord_user_id is withheld), so the new
-- columns need an explicit SELECT grant too, or every profile fetch that names them fails.

alter table public.member_profiles
  add column if not exists joined_month date,
  add column if not exists joined_month_source text;

alter table public.member_profiles
  drop constraint if exists member_profiles_joined_month_first_day;
alter table public.member_profiles
  add constraint member_profiles_joined_month_first_day
  check (joined_month is null or extract(day from joined_month) = 1);

alter table public.member_profiles
  drop constraint if exists member_profiles_joined_month_source_check;
alter table public.member_profiles
  add constraint member_profiles_joined_month_source_check
  check (joined_month_source is null or joined_month_source in ('self_intro', 'member'));

comment on column public.member_profiles.joined_month is
  'F研の入会時期 (first day of the month). From the first self-intro post, or set by the member (issue #324).';
comment on column public.member_profiles.joined_month_source is
  'self_intro = filled by scripts/sync_member_joined_month.py; member = set by the member themselves (never overwritten by the sync).';

grant select (joined_month, joined_month_source) on public.member_profiles to anon, authenticated;
grant update (joined_month, joined_month_source) on public.member_profiles to authenticated;
