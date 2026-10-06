-- 相談テーママッチング (GitHub issue #322): a member writes a consultation theme on the map,
-- ふぁいにゃ posts it anonymously to the ゆるマッチング channel, members raise a hand (✋), and once
-- enough of them with overlapping availability have gathered it becomes a ゆるマッチング group
-- (same date poll / voice channel / reminder / survey flow as regular matching).
--
-- Who wrote a theme must never be visible to anyone else while it is recruiting, so:
--   * members can read ONLY their own rows (RLS, keyed on current_member_nickname());
--   * there are no insert/update/delete policies -- posting and withdrawing go through the
--     consultation-request Edge Function (service role), which also posts to / deletes from
--     Discord, and the follow-up batch (scripts/process_consultation_requests.py, service role)
--     counts hands, forms the group, and closes the theme;
--   * column-level SELECT leaves out the Discord bookkeeping columns.
--
-- Lifecycle: recruiting -> matched (group formed) | expired (deadline, 7 days) | withdrawn
-- (by the member, or the Discord post was deleted by an admin).

create table if not exists public.consultation_requests (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null references public.member_profiles (nickname) on update cascade on delete cascade,
  body text not null check (char_length(body) between 5 and 500),
  status text not null default 'recruiting' check (status in ('recruiting', 'matched', 'expired', 'withdrawn')),
  discord_message_id text,
  posted_at timestamptz not null default now(),
  deadline_at timestamptz not null default (now() + interval '7 days'),
  responders jsonb not null default '[]'::jsonb,
  responder_count integer not null default 0,
  optin_notified_user_ids text[] not null default '{}',
  group_id uuid references public.member_match_groups (id) on delete set null,
  closed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.consultation_requests is
  '相談テーママッチング (issue #322). Readable only by the member who wrote it; written only by the consultation-request Edge Function and scripts/process_consultation_requests.py (service role).';
comment on column public.consultation_requests.body is
  'The theme exactly as the member wrote it; ふぁいにゃ posts it verbatim (the input screen warns not to include identifying details).';
comment on column public.consultation_requests.responders is
  'Hand-raisers counted so far, oldest first: [{"nickname": ..., "first_seen_at": ...}]. Only opted-in members whose availability overlaps the group''s remaining common slots count. first_seen_at is when the batch first saw the reaction (Discord does not expose reaction times), which decides first-come order.';
comment on column public.consultation_requests.responder_count is
  'How many hand-raisers currently count toward the group (shown to the member as n / 3).';
comment on column public.consultation_requests.optin_notified_user_ids is
  'Discord ids of hand-raisers who were not opted in (or had no availability) and were already DMed to turn ゆるマッチング on, so they are DMed only once per theme.';
comment on column public.consultation_requests.group_id is
  'The member_match_groups row created when the theme matched.';

drop trigger if exists set_consultation_requests_updated_at on public.consultation_requests;
create trigger set_consultation_requests_updated_at
before update on public.consultation_requests
for each row
execute function public.set_updated_at();

create index if not exists consultation_requests_member_idx on public.consultation_requests (member_nickname);
create index if not exists consultation_requests_status_idx on public.consultation_requests (status);

alter table public.consultation_requests enable row level security;

revoke all on public.consultation_requests from anon, authenticated;
grant select (id, member_nickname, body, status, posted_at, deadline_at, responder_count, closed_at, created_at)
  on public.consultation_requests to authenticated;

drop policy if exists "consultation requests are readable by owner" on public.consultation_requests;
create policy "consultation requests are readable by owner"
on public.consultation_requests
for select
to authenticated
using (member_nickname = public.current_member_nickname());
