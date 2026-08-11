-- Block accidental external publication of member profile fields.
-- This is intentionally separate from data sync scripts: automation may enrich
-- profile data, but may not enable external-public flags.

create or replace function public.prevent_implicit_public_profile_publication()
returns trigger
language plpgsql
as $$
declare
  publication_enable_allowed boolean :=
    coalesce(current_setting('app.allow_public_profile_publication', true), '') = 'on';
begin
  if publication_enable_allowed then
    return new;
  end if;

  if tg_op = 'INSERT' then
    if new.nickname_public
      or new.avatar_public
      or new.self_intro_public
      or new.location_public
      or new.links_public
    then
      raise exception 'External profile publication flags can only be enabled via update_member_profile_publication()'
        using errcode = '42501';
    end if;
    return new;
  end if;

  if (not old.nickname_public and new.nickname_public)
    or (not old.avatar_public and new.avatar_public)
    or (not old.self_intro_public and new.self_intro_public)
    or (not old.location_public and new.location_public)
    or (not old.links_public and new.links_public)
  then
    raise exception 'External profile publication flags can only be enabled via update_member_profile_publication()'
      using errcode = '42501';
  end if;

  return new;
end;
$$;

drop trigger if exists prevent_implicit_public_profile_publication on public.member_profiles;
create trigger prevent_implicit_public_profile_publication
before insert or update on public.member_profiles
for each row
execute function public.prevent_implicit_public_profile_publication();

create or replace function public.update_member_profile_publication(
  target_nickname text,
  field_name text,
  enabled boolean
)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  updated_count integer;
begin
  if field_name not in (
    'nickname_public',
    'avatar_public',
    'self_intro_public',
    'location_public',
    'links_public'
  ) then
    raise exception 'Invalid member profile publication field: %', field_name
      using errcode = '22023';
  end if;

  perform set_config('app.allow_public_profile_publication', 'on', true);

  execute format(
    'update public.member_profiles set %I = $1 where nickname = $2',
    field_name
  )
  using enabled, target_nickname;

  get diagnostics updated_count = row_count;
  if updated_count = 0 then
    raise exception 'Member profile not found: %', target_nickname
      using errcode = '02000';
  end if;
end;
$$;

revoke all on function public.update_member_profile_publication(text, text, boolean) from public;
grant execute on function public.update_member_profile_publication(text, text, boolean) to anon, authenticated;

notify pgrst, 'reload schema';
