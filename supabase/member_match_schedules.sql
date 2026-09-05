-- Scheduling follow-up for ゆるマッチング groups (member proposal, itチーム
-- Discord message from memeto0531, 2026-09-05): after a group of 4 is
-- matched, propose 3 candidate dates for the shared day-of-week/time-slot,
-- let the group react to vote, auto-confirm once 3+ of them react to the
-- same option, and spin up a temporary voice channel scoped to that group
-- for the confirmed date.
--
-- Written only by scripts/run_member_matching.py (posting the proposal) and
-- scripts/process_member_match_schedules.py (confirming / creating the
-- voice channel / cleaning it up), both via the service role key. No
-- insert/update/delete policies for anon/authenticated, matching
-- member_match_groups.

create table if not exists public.member_match_schedules (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.member_match_groups (id) on delete cascade,
  proposed_dates timestamptz[] not null,
  discord_message_id text,
  status text not null default 'proposed' check (status in ('proposed', 'confirmed', 'expired')),
  confirmed_date timestamptz,
  confirmed_reaction_count integer,
  voice_channel_id text,
  voice_channel_deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.member_match_schedules is
  'Date-scheduling follow-up for one member_match_groups row: 3 proposed dates posted as a reaction poll, confirmed once 3+ group members react to the same option, with an optional temporary voice channel for the confirmed date. Written by the matching batch scripts with the service role key only.';
comment on column public.member_match_schedules.proposed_dates is
  'The 3 candidate datetimes offered (next 3 occurrences of the group''s matched day-of-week, at a fixed time-of-day for the matched time_slot).';
comment on column public.member_match_schedules.discord_message_id is
  'The reaction-poll message (1️⃣/2️⃣/3️⃣), separate from the original match announcement.';
comment on column public.member_match_schedules.voice_channel_id is
  'Temporary Discord voice channel created for the confirmed date, scoped to just this group via permission overwrites. Deleted (and voice_channel_deleted_at set) after the event has passed.';

drop trigger if exists set_member_match_schedules_updated_at on public.member_match_schedules;
create trigger set_member_match_schedules_updated_at
before update on public.member_match_schedules
for each row
execute function public.set_updated_at();

create index if not exists member_match_schedules_group_id_idx on public.member_match_schedules (group_id);
create index if not exists member_match_schedules_status_idx on public.member_match_schedules (status);

alter table public.member_match_schedules enable row level security;

drop policy if exists "member match schedules are publicly readable" on public.member_match_schedules;
create policy "member match schedules are publicly readable"
on public.member_match_schedules
for select
to anon, authenticated
using (true);
