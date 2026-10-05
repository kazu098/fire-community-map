-- Discord login (GitHub issue #253): the built-in Discord provider is disabled
-- (it always requests the `email` scope), and its only user was deleted on
-- 2026-10-06. Members sign in only through the custom provider
-- `custom:discord-id` (see member_auth_custom_provider.sql), so the member
-- lookup no longer accepts the built-in provider.

create or replace function public.current_member_nickname()
returns text
language sql
security definer
set search_path = public
stable
as $$
  select mp.nickname
  from auth.identities i
  join public.member_profiles mp on mp.discord_user_id = i.provider_id
  where i.user_id = auth.uid()
    and i.provider = 'custom:discord-id'
  limit 1;
$$;

revoke execute on function public.current_member_nickname() from public, anon;
grant execute on function public.current_member_nickname() to authenticated;
