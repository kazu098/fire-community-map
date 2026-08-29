-- Member matching (プチおせっかい): availability-based random matching.
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
  interval_days integer not null default 7 check (interval_days in (3, 7, 14, 30)),
  last_matched_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.member_matching_settings is
  'Per-member opt-in flag and matching interval for the availability-based random matching (プチおせっかい) feature.';
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

-- Only opted_in/interval_days are member-editable. last_matched_at is
-- reserved for the matching batch, which runs with the service role key
-- and therefore bypasses RLS/column grants.
revoke update on public.member_matching_settings from anon, authenticated;
grant update (opted_in, interval_days) on public.member_matching_settings to anon, authenticated;

drop policy if exists "member matching settings are publicly updatable" on public.member_matching_settings;
create policy "member matching settings are publicly updatable"
on public.member_matching_settings
for update
to anon, authenticated
using (true)
with check (true);

-- ================================================================
-- Availability (weekday x time-of-day slots)
-- ================================================================

create table if not exists public.member_availability (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on delete cascade,
  day_of_week text not null check (
    day_of_week in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
  ),
  time_slot text not null check (
    time_slot in ('morning', 'afternoon', 'evening')
  ),
  created_at timestamptz not null default now(),
  unique (member_nickname, day_of_week, time_slot)
);

comment on table public.member_availability is
  'Self-reported weekday x time-of-day availability slots for the availability-based random matching (プチおせっかい) feature. Not tied to similarity/tags.';

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

create table if not exists public.member_matches (
  id uuid primary key default gen_random_uuid(),
  member_a text not null,
  member_b text not null,
  day_of_week text not null check (
    day_of_week in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
  ),
  time_slot text not null check (
    time_slot in ('morning', 'afternoon', 'evening')
  ),
  discord_message_id text,
  posted_at timestamptz,
  created_at timestamptz not null default now(),
  constraint member_matches_distinct_members check (member_a <> member_b)
);

comment on table public.member_matches is
  'History of matched pairs from the availability-based random matching batch. Used to compute the re-match cooldown and as an audit trail. Written by the batch script with the service role key only.';

create index if not exists member_matches_member_a_idx on public.member_matches (member_a);
create index if not exists member_matches_member_b_idx on public.member_matches (member_b);
create index if not exists member_matches_created_at_idx on public.member_matches (created_at);

alter table public.member_matches enable row level security;

drop policy if exists "member matches are publicly readable" on public.member_matches;
create policy "member matches are publicly readable"
on public.member_matches
for select
to anon, authenticated
using (true);
