-- Migrate member_availability / member_match_groups from 3 coarse time_slot values
-- (morning/afternoon/evening) to 1-hour granularity, matching the hourly grain already
-- used by member_availability_overrides. Apply this ONCE, manually, in the Supabase SQL
-- Editor, before deploying the app change that switches the ゆるマッチング availability
-- grid UI to hourly (index.html's MATCHING_HOURS). Safe to re-run: each block is guarded
-- to no-op if already applied.
--
-- Background: itチームのDiscordでの相談(2026-09-23、たびおさんの提案)。夜21:00固定の
-- 開催提案が遅いという声を受け、曜日×時間帯の3段階をやめて1時間刻みのドラッグ登録に統一
-- することにした。既存データの引き継ぎルール(かずさんとの相談で決定):
--   morning   -> 9, 10, 11 時   (9:00-12:00)
--   afternoon -> 13, 14, 15, 16, 17 時 (13:00-18:00)
--   evening   -> 18, 19, 20 時  (18:00-21:00)
-- 18時が昼/夜どちらのレンジにも含まれるのは意図的な重複(昼の遅め〜夜の早めを取りこぼさ
-- ないため)。移行後は各自「特定日の例外」と同じ1時間グリッドで手動調整してもらう運用。

-- ================================================================
-- member_availability: expand each (day_of_week, time_slot) row into one row per hour.
-- ================================================================
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'member_availability' and column_name = 'time_slot'
  ) then
    alter table public.member_availability add column if not exists hour integer;

    -- The old unique constraint is (member_nickname, day_of_week, time_slot); expanding a
    -- single slot into multiple hourly rows needs several rows sharing the same time_slot,
    -- so it has to go before the insert below.
    alter table public.member_availability
      drop constraint if exists member_availability_member_nickname_day_of_week_time_slot_key;

    insert into public.member_availability (member_nickname, day_of_week, time_slot, hour)
    select m.member_nickname, m.day_of_week, m.time_slot, h
    from public.member_availability m,
      unnest(case m.time_slot
        when 'morning' then array[9, 10, 11]
        when 'afternoon' then array[13, 14, 15, 16, 17]
        when 'evening' then array[18, 19, 20]
      end) as h
    where m.hour is null;

    -- The original rows (pre-expansion) never got a value in the new hour column.
    delete from public.member_availability where hour is null;

    alter table public.member_availability alter column hour set not null;
    alter table public.member_availability drop column time_slot;
  end if;
end $$;

alter table public.member_availability drop constraint if exists member_availability_hour_check;
alter table public.member_availability
  add constraint member_availability_hour_check check (hour >= 0 and hour <= 23);

alter table public.member_availability
  drop constraint if exists member_availability_member_nickname_day_of_week_hour_key;
alter table public.member_availability
  add constraint member_availability_member_nickname_day_of_week_hour_key unique (member_nickname, day_of_week, hour);

comment on column public.member_availability.hour is
  'Hour of day in JST (0-23), the start of a 1-hour block. E.g. 10 means 10:00-11:00. The UI only offers 7-23, matching member_availability_overrides.';

-- ================================================================
-- member_match_groups: pick one representative hour per historical row (audit trail, not
-- reused for future matching decisions -- only new matches need a real hour going forward).
-- ================================================================
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'member_match_groups' and column_name = 'time_slot'
  ) then
    alter table public.member_match_groups add column if not exists hour integer;

    update public.member_match_groups
    set hour = case time_slot when 'morning' then 10 when 'afternoon' then 14 when 'evening' then 19 end
    where hour is null;

    alter table public.member_match_groups alter column hour set not null;
    alter table public.member_match_groups drop column time_slot;
  end if;
end $$;

alter table public.member_match_groups drop constraint if exists member_match_groups_hour_check;
alter table public.member_match_groups
  add constraint member_match_groups_hour_check check (hour >= 0 and hour <= 23);

notify pgrst, 'reload schema';
