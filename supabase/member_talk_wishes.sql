-- 「話してみたい人」リスト: a member privately registers other members they would like to talk
-- to, and the ゆるマッチング batch (scripts/run_member_matching.py) tries to put them in the
-- same group.
--
-- Private to the registrant:
--   * members can read / add / remove ONLY their own rows (RLS keyed on current_member_nickname());
--   * anon has no access at all;
--   * the matching batch reads every row with the service role (bypasses RLS). The batch only
--     uses the list to bias grouping and never writes it to Discord or any table another member
--     can read, so being matched with someone does not reveal who wished for whom.

create table if not exists public.member_talk_wishes (
  member_nickname text not null references public.member_profiles (nickname) on update cascade on delete cascade,
  target_nickname text not null references public.member_profiles (nickname) on update cascade on delete cascade,
  created_at timestamptz not null default now(),
  primary key (member_nickname, target_nickname),
  check (member_nickname <> target_nickname)
);

comment on table public.member_talk_wishes is
  '話してみたい人リスト. Readable/writable only by the member who owns the row; read by the ゆるマッチング batch (service role) to bias grouping. Never exposed to the target.';

alter table public.member_talk_wishes enable row level security;

revoke all on public.member_talk_wishes from anon, authenticated;
grant select, insert, delete on public.member_talk_wishes to authenticated;

drop policy if exists "talk wishes are readable by owner" on public.member_talk_wishes;
create policy "talk wishes are readable by owner"
on public.member_talk_wishes
for select
to authenticated
using (member_nickname = public.current_member_nickname());

drop policy if exists "talk wishes are insertable by owner" on public.member_talk_wishes;
create policy "talk wishes are insertable by owner"
on public.member_talk_wishes
for insert
to authenticated
with check (member_nickname = public.current_member_nickname());

drop policy if exists "talk wishes are deletable by owner" on public.member_talk_wishes;
create policy "talk wishes are deletable by owner"
on public.member_talk_wishes
for delete
to authenticated
using (member_nickname = public.current_member_nickname());

-- Rollback:
-- drop table if exists public.member_talk_wishes;
