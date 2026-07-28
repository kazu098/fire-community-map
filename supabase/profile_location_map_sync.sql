-- Keep map display text in sync when a member edits their residence text.
-- This intentionally does not update coordinates or normalized prefecture fields.

create or replace function public.sync_member_profile_location_to_map()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.location_text is distinct from old.location_text then
    update public.member_locations
    set location_text = new.location_text
    where nickname = new.nickname
      and new.location_text is not null
      and btrim(new.location_text) <> '';
  end if;
  return new;
end;
$$;

drop trigger if exists sync_member_profile_location_to_map on public.member_profiles;
create trigger sync_member_profile_location_to_map
after update on public.member_profiles
for each row
execute function public.sync_member_profile_location_to_map();

update public.member_locations l
set location_text = p.location_text
from public.member_profiles p
where p.nickname = l.nickname
  and p.location_text is not null
  and btrim(p.location_text) <> ''
  and l.location_text is distinct from p.location_text;
