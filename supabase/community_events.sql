-- Community events: upcoming and past Discord/community event records.
-- Rows are curated from Discord announcements or recap posts, then written by
-- scripts/load_community_events.py with the service role key.

create table if not exists public.community_events (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  tags text[] not null default '{}',
  starts_at timestamptz not null,
  ends_at timestamptz,
  format text not null check (format in ('online', 'offline', 'hybrid', 'unknown')),
  prefecture text,
  location_label text,
  participant_count integer check (participant_count is null or participant_count >= 0),
  participation_note text,
  summary text,
  highlights text,
  learnings text,
  discord_channel_name text,
  discord_message_id text unique,
  discord_permalink text,
  cancelled_at timestamptz,
  created_at timestamptz not null default now()
);

comment on table public.community_events is
  'Curated event records for upcoming and past community events. Does not store Discord user IDs or participant identities.';

comment on column public.community_events.tags is
  'Small display tags such as オンライン, オフ会, 勉強会, 交流会. Tags are not used as primary navigation in the initial UI.';

comment on column public.community_events.starts_at is
  'Used by the frontend to split upcoming and past events.';

create index if not exists community_events_starts_at_idx
  on public.community_events (starts_at desc);

create index if not exists community_events_cancelled_at_idx
  on public.community_events (cancelled_at)
  where cancelled_at is not null;

alter table public.community_events enable row level security;

drop policy if exists "community events are publicly readable" on public.community_events;
create policy "community events are publicly readable"
on public.community_events
for select
to anon, authenticated
using (true);

-- No insert/update/delete policies for anon/authenticated: event records are
-- curated operational data and are written only via the service role.

notify pgrst, 'reload schema';
