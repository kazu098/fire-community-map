-- Add a "興味あるテーマや話題" (chat_topic) category, for topics a member wants
-- to talk about -- distinct from "趣味・興味" (interest), which describes who
-- they are rather than what they'd like to discuss in a ゆるマッチング match.
-- Apply this once to existing Supabase databases before adding chat_topic tags.

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
      'affiliation',
      'chat_topic'
    )
  );

notify pgrst, 'reload schema';
