-- Allow newly curated consultation channels in community_posts.

alter table public.community_posts
  drop constraint if exists community_posts_content_type_check;

alter table public.community_posts
  add constraint community_posts_content_type_check
  check (
    content_type in (
      'book',
      'travel',
      'money_consultation',
      'care_medical',
      'parenting',
      'real_estate'
    )
  );

notify pgrst, 'reload schema';
