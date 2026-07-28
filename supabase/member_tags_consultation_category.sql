-- Allow a separate "相談できること" tag category.
-- Apply this once to existing Supabase databases before adding consultation tags.

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
      'interest',
      'affiliation'
    )
  );

notify pgrst, 'reload schema';
