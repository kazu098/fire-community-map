-- Date-specific availability overrides for the ゆるマッチング feature (see
-- docs/yuru-matching.md and the itチーム Discord thread 2026-09-14/15,
-- https://discord.com/channels/1389921372683112539/1514597598357491742/1549054660126580778).
--
-- The recurring day_of_week x time_slot pattern in member_availability (3
-- coarse slots: morning/afternoon/evening) stays the default input. This
-- table lets a member additionally mark specific calendar dates (typically
-- the next 3 weeks to a month) as available or unavailable, at 1-hour
-- granularity, for weeks where their usual pattern doesn't hold. Hourly was
-- chosen over the 3-slot enum here because that's what was actually
-- requested (Hiro-shi@GL's proposal explicitly says "1時間ごと" is too much
-- to ask app-wide, but wants it for this specific-date override). Same
-- open-editing + audit-trail pattern as member_availability (anon
-- insert/select/delete, no update needed since entries are toggled by
-- delete+insert).

create table if not exists public.member_availability_overrides (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on delete cascade,
  override_date date not null,
  hour integer not null check (hour >= 0 and hour <= 23),
  is_available boolean not null,
  created_at timestamptz not null default now(),
  unique (member_nickname, override_date, hour)
);

comment on table public.member_availability_overrides is
  'Date-specific, hourly availability overrides for ゆるマッチング (available or unavailable), on top of the coarser recurring day_of_week x time_slot pattern in member_availability. Typically registered for the next few weeks.';
comment on column public.member_availability_overrides.hour is
  'Hour of day in JST (0-23), the start of a 1-hour block. E.g. 10 means 10:00-11:00.';
comment on column public.member_availability_overrides.is_available is
  'true = explicitly available on this date/hour even if the recurring pattern says no; false = explicitly unavailable even if the recurring pattern says yes.';

create index if not exists member_availability_overrides_member_nickname_idx
  on public.member_availability_overrides (member_nickname);
create index if not exists member_availability_overrides_date_idx
  on public.member_availability_overrides (override_date);

alter table public.member_availability_overrides enable row level security;

drop policy if exists "member availability overrides are publicly readable" on public.member_availability_overrides;
create policy "member availability overrides are publicly readable"
on public.member_availability_overrides
for select
to anon, authenticated
using (true);

drop policy if exists "member availability overrides are publicly insertable" on public.member_availability_overrides;
create policy "member availability overrides are publicly insertable"
on public.member_availability_overrides
for insert
to anon, authenticated
with check (true);

drop policy if exists "member availability overrides are publicly deletable" on public.member_availability_overrides;
create policy "member availability overrides are publicly deletable"
on public.member_availability_overrides
for delete
to anon, authenticated
using (true);
