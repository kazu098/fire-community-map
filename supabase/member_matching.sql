-- Member matching (ゆるマッチング): availability-based random matching.
-- See GitHub issue #76 for the design background. Unlike member_tags/member_links
-- (fully open write), matching participation is opt-in and stores a per-member
-- schedule, so writes are scoped to just the columns/rows each member needs to
-- self-manage, following the same open-editing + audit-trail pattern used
-- elsewhere in this schema (no per-member auth in this app yet).

-- ================================================================
-- Opt-in + matching frequency
-- ================================================================

create table if not exists public.member_matching_settings (
  member_nickname text primary key references public.member_profiles (nickname) on delete cascade,
  opted_in boolean not null default false,
  interval_days integer not null default 7 check (interval_days in (2, 3, 7, 14, 30)),
  last_matched_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.member_matching_settings is
  'Per-member opt-in flag and matching interval for the availability-based random matching (ゆるマッチング) feature.';
comment on column public.member_matching_settings.interval_days is
  'How often this member wants to be matched, in days. A member is eligible again once interval_days have passed since last_matched_at.';
comment on column public.member_matching_settings.last_matched_at is
  'Set by the matching batch (service role) when this member is matched. Not writable by members.';

drop trigger if exists set_member_matching_settings_updated_at on public.member_matching_settings;
create trigger set_member_matching_settings_updated_at
before update on public.member_matching_settings
for each row
execute function public.set_updated_at();

alter table public.member_matching_settings enable row level security;

drop policy if exists "member matching settings are publicly readable" on public.member_matching_settings;
create policy "member matching settings are publicly readable"
on public.member_matching_settings
for select
to anon, authenticated
using (true);

drop policy if exists "member matching settings are publicly insertable" on public.member_matching_settings;
create policy "member matching settings are publicly insertable"
on public.member_matching_settings
for insert
to anon, authenticated
with check (true);

-- Only opted_in/interval_days are meant to be member-editable. last_matched_at
-- is reserved for the matching batch, which runs with the service role key
-- and therefore bypasses RLS/column grants.
--
-- Two other columns need an UPDATE grant too, even though members never
-- intend to change their values, because the client upserts via PostgREST's
-- `Prefer: resolution=merge-duplicates` (INSERT ... ON CONFLICT (member_nickname)
-- DO UPDATE SET <every submitted column> = excluded.<column>), and Postgres
-- checks column-level UPDATE privilege for every column in that SET list --
-- both member_nickname (the conflict/PK column, always re-set to its own
-- value) and updated_at (written by the set_updated_at trigger on every
-- UPDATE, which also requires privilege on the assigned column). Omitting
-- either makes every member-initiated save fail with "permission denied".
revoke update on public.member_matching_settings from anon, authenticated;
grant update (member_nickname, opted_in, interval_days, updated_at) on public.member_matching_settings to anon, authenticated;

drop policy if exists "member matching settings are publicly updatable" on public.member_matching_settings;
create policy "member matching settings are publicly updatable"
on public.member_matching_settings
for update
to anon, authenticated
using (true)
with check (true);

-- ================================================================
-- Availability (weekday x hour)
-- ================================================================
-- Was originally 3 coarse time_slot values (morning/afternoon/evening); changed to
-- 1-hour granularity (see itチームDiscord 2026-09-23, たびおさんの提案-- a fixed
-- 21:00 evening start felt late for some members) to match the hourly grain already
-- used by member_availability_overrides. For an existing database, apply
-- member_availability_hourly_migration.sql once instead of this create table
-- (which only runs on a fresh install).

create table if not exists public.member_availability (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on delete cascade,
  day_of_week text not null check (
    day_of_week in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
  ),
  hour integer not null check (hour >= 0 and hour <= 23),
  created_at timestamptz not null default now(),
  unique (member_nickname, day_of_week, hour)
);

comment on table public.member_availability is
  'Self-reported weekday x hour availability slots for the availability-based random matching (ゆるマッチング) feature. Not tied to similarity/tags.';
comment on column public.member_availability.hour is
  'Hour of day in JST (0-23), the start of a 1-hour block. E.g. 10 means 10:00-11:00. The UI only offers 7-23 (see MATCHING_HOURS in index.html), matching member_availability_overrides.';

create index if not exists member_availability_member_nickname_idx
  on public.member_availability (member_nickname);

alter table public.member_availability enable row level security;

drop policy if exists "member availability is publicly readable" on public.member_availability;
create policy "member availability is publicly readable"
on public.member_availability
for select
to anon, authenticated
using (true);

drop policy if exists "member availability is publicly insertable" on public.member_availability;
create policy "member availability is publicly insertable"
on public.member_availability
for insert
to anon, authenticated
with check (true);

drop policy if exists "member availability is publicly deletable" on public.member_availability;
create policy "member availability is publicly deletable"
on public.member_availability
for delete
to anon, authenticated
using (true);

-- ================================================================
-- Match history (audit trail + cooldown source)
-- ================================================================
-- Written only by the matching batch via the service role key. No
-- insert/update/delete policies for anon/authenticated.
--
-- One row per matched group (default size 3, falls back to 2) plus a join
-- table for its members, rather than fixed member_a/member_b columns, so
-- the batch can group more than two people without a schema change every
-- time the target group size changes.

create table if not exists public.member_match_groups (
  id uuid primary key default gen_random_uuid(),
  day_of_week text not null check (
    day_of_week in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
  ),
  hour integer not null check (hour >= 0 and hour <= 23),
  discord_message_id text,
  posted_at timestamptz,
  created_at timestamptz not null default now()
);

comment on table public.member_match_groups is
  'A matched group (default size 3, falls back to 2) from the availability-based random matching batch. Used to compute the re-match cooldown (via member_match_group_members) and as an audit trail. Written by the batch script with the service role key only.';
comment on column public.member_match_groups.hour is
  'The overlapping hour (JST, 0-23) the group shared, chosen at random among their common availability. Was time_slot (morning/afternoon/evening) before member_availability moved to hourly granularity -- see member_availability_hourly_migration.sql.';

create index if not exists member_match_groups_created_at_idx on public.member_match_groups (created_at);

create table if not exists public.member_match_group_members (
  group_id uuid not null references public.member_match_groups (id) on delete cascade,
  member_nickname text not null,
  primary key (group_id, member_nickname)
);

comment on table public.member_match_group_members is
  'Members belonging to each member_match_groups row. Every 2-member combination within a group counts toward the re-match cooldown, not just the pair that happened to be grouped together this time.';

create index if not exists member_match_group_members_nickname_idx on public.member_match_group_members (member_nickname);

alter table public.member_match_groups enable row level security;
alter table public.member_match_group_members enable row level security;

drop policy if exists "member match groups are publicly readable" on public.member_match_groups;
create policy "member match groups are publicly readable"
on public.member_match_groups
for select
to anon, authenticated
using (true);

drop policy if exists "member match group members are publicly readable" on public.member_match_group_members;
create policy "member match group members are publicly readable"
on public.member_match_group_members
for select
to anon, authenticated
using (true);
