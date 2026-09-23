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
  confirmed_source text,
  thread_id text,
  thread_suggested_date timestamptz,
  thread_confirmation_message_id text,
  thread_confirmation_date timestamptz,
  thread_confirmation_reaction_count integer,
  voice_channel_id text,
  voice_channel_deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.member_match_schedules
  add column if not exists confirmed_source text,
  add column if not exists thread_id text,
  add column if not exists thread_suggested_date timestamptz,
  add column if not exists thread_confirmation_message_id text,
  add column if not exists thread_confirmation_date timestamptz,
  add column if not exists thread_confirmation_reaction_count integer;

comment on table public.member_match_schedules is
  'Date-scheduling follow-up for one member_match_groups row: 3 proposed dates posted as a reaction poll, confirmed once 3+ group members react to the same option, with an optional temporary voice channel for the confirmed date. Written by the matching batch scripts with the service role key only.';
comment on column public.member_match_schedules.proposed_dates is
  'The 3 candidate datetimes offered (next 3 occurrences of the group''s matched day-of-week, at the group''s matched hour).';
comment on column public.member_match_schedules.discord_message_id is
  'The reaction-poll message (1️⃣/2️⃣/3️⃣), separate from the original match announcement.';
comment on column public.member_match_schedules.confirmed_source is
  'How the schedule was confirmed: reaction_poll for the original 1️⃣/2️⃣/3️⃣ choices, or thread_confirmation for an extra date discussed in the Discord thread and confirmed with ✅.';
comment on column public.member_match_schedules.thread_id is
  'Discord thread channel checked for free-text date negotiation after the initial 3 reaction-poll choices.';
comment on column public.member_match_schedules.thread_suggested_date is
  'A non-poll date inferred from group-member text in the Discord thread before posting the ✅ confirmation prompt.';
comment on column public.member_match_schedules.thread_confirmation_message_id is
  'The Discord thread message asking the group to confirm an inferred non-poll date with ✅.';
comment on column public.member_match_schedules.thread_confirmation_date is
  'The non-poll datetime being confirmed by thread_confirmation_message_id.';
comment on column public.member_match_schedules.thread_confirmation_reaction_count is
  'The group-member ✅ count observed on the thread confirmation prompt. The final count is also copied to confirmed_reaction_count once confirmed.';
comment on column public.member_match_schedules.voice_channel_id is
  'Temporary Discord voice channel created for the confirmed date, scoped to just this group via permission overwrites. Deleted (and voice_channel_deleted_at set) after the event has passed.';

drop trigger if exists set_member_match_schedules_updated_at on public.member_match_schedules;
create trigger set_member_match_schedules_updated_at
before update on public.member_match_schedules
for each row
execute function public.set_updated_at();

create index if not exists member_match_schedules_group_id_idx on public.member_match_schedules (group_id);
create index if not exists member_match_schedules_status_idx on public.member_match_schedules (status);
create index if not exists member_match_schedules_thread_confirmation_message_id_idx
  on public.member_match_schedules (thread_confirmation_message_id);

alter table public.member_match_schedules enable row level security;

drop policy if exists "member match schedules are publicly readable" on public.member_match_schedules;
create policy "member match schedules are publicly readable"
on public.member_match_schedules
for select
to anon, authenticated
using (true);
