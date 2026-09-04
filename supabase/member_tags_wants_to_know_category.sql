-- Allow a separate "知りたいこと" tag category, paired with the existing
-- "相談できること" (consultation) category for matching members who want to
-- learn about something with members who can advise on it.
-- Apply this once to existing Supabase databases before adding wants_to_know tags.

alter table public.member_tags
  drop constraint if exists member_tags_category_check;

alter table public.member_tags
  add constraint member_tags_category_check
  check (
    category in (
      'investment_style',
      'fire_status',
      'mbti',
      'skill',
      'consultation',
      'wants_to_know',
      'interest',
      'affiliation'
    )
  );

notify pgrst, 'reload schema';
