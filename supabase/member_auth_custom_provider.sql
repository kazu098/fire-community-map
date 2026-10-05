-- Discord login without collecting email (GitHub issue #253).
--
-- The built-in Discord provider always requests the `email` scope, so sign-in
-- moves to a Supabase custom OAuth2 provider `custom:discord-id` that requests
-- only `identify`. Its UserInfo URL is api/discord-userinfo.js on this site,
-- which returns the Discord user id as `sub`, so auth.identities.provider_id is
-- the Discord user id exactly as with the built-in provider.
--
-- current_member_nickname() accepts both providers during the switch-over;
-- drop 'discord' once the built-in provider is disabled.

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
    and i.provider in ('discord', 'custom:discord-id')
  limit 1;
$$;

revoke execute on function public.current_member_nickname() from public, anon;
grant execute on function public.current_member_nickname() to authenticated;
