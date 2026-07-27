-- Add external publication settings for member profiles.
-- Apply this once to the Supabase database before using the public toggles.

alter table public.member_profiles add column if not exists nickname_public boolean not null default false;
alter table public.member_profiles add column if not exists avatar_public boolean not null default false;
alter table public.member_profiles add column if not exists self_intro_public boolean not null default false;
alter table public.member_profiles add column if not exists location_public boolean not null default false;
alter table public.member_profiles add column if not exists links_public boolean not null default false;

comment on column public.member_profiles.nickname_public is
  'When true, nickname may be shown on the external public profile directory.';
comment on column public.member_profiles.avatar_public is
  'When true, avatar_url may be shown on the external public profile directory.';
comment on column public.member_profiles.self_intro_public is
  'When true, self_intro_text may be shown on the external public profile directory.';
comment on column public.member_profiles.location_public is
  'When true, location_text may be shown on the external public profile directory.';
comment on column public.member_profiles.links_public is
  'When true, non-memo member_links may be shown on the external public profile directory.';

grant update (
  nickname_public,
  avatar_public,
  self_intro_public,
  location_public,
  links_public
) on public.member_profiles to anon, authenticated;

create table if not exists public.member_profile_publication_edits (
  id uuid primary key default gen_random_uuid(),
  member_nickname text not null,
  field_name text not null check (
    field_name in ('nickname_public', 'avatar_public', 'self_intro_public', 'location_public', 'links_public')
  ),
  old_value boolean,
  new_value boolean,
  edited_at timestamptz not null default now()
);

comment on table public.member_profile_publication_edits is
  'Append-only audit trail of external publication setting changes, written by trigger only.';

create index if not exists member_profile_publication_edits_member_nickname_idx
  on public.member_profile_publication_edits (member_nickname);

alter table public.member_profile_publication_edits enable row level security;

drop policy if exists "member profile publication edits are publicly readable" on public.member_profile_publication_edits;

create or replace function public.log_member_profile_publication_edit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.nickname_public is distinct from old.nickname_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'nickname_public', old.nickname_public, new.nickname_public);
  end if;
  if new.avatar_public is distinct from old.avatar_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'avatar_public', old.avatar_public, new.avatar_public);
  end if;
  if new.self_intro_public is distinct from old.self_intro_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'self_intro_public', old.self_intro_public, new.self_intro_public);
  end if;
  if new.location_public is distinct from old.location_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'location_public', old.location_public, new.location_public);
  end if;
  if new.links_public is distinct from old.links_public then
    insert into public.member_profile_publication_edits (member_nickname, field_name, old_value, new_value)
    values (new.nickname, 'links_public', old.links_public, new.links_public);
  end if;
  return new;
end;
$$;

drop trigger if exists log_member_profile_publication_edits on public.member_profiles;
create trigger log_member_profile_publication_edits
after update on public.member_profiles
for each row
execute function public.log_member_profile_publication_edit();

create or replace view public.public_member_profiles as
select
  p.id as member_id,
  case when p.nickname_public then p.nickname else null end as display_nickname,
  case when p.avatar_public then p.avatar_url else null end as display_avatar_url,
  case when p.self_intro_public then p.self_intro_text else null end as display_self_intro_text,
  case when p.location_public then p.location_text else null end as display_location_text,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'category', t.category,
          'value', t.value,
          'sort_order', t.sort_order
        )
        order by t.category, t.sort_order, t.created_at
      )
      from public.member_tags t
      where t.member_nickname = p.nickname
        and t.category <> 'affiliation'
    ),
    '[]'::jsonb
  ) as tags,
  case
    when p.links_public then coalesce(
      (
        select jsonb_agg(
          jsonb_build_object(
            'label', l.label,
            'url', l.url
          )
          order by l.created_at
        )
        from public.member_links l
        where l.member_nickname = p.nickname
          and l.label <> '個人メモ'
      ),
      '[]'::jsonb
    )
    else '[]'::jsonb
  end as links
from public.member_profiles p;

comment on view public.public_member_profiles is
  'External public profile directory. Non-public fields are nulled and personal memo links are always excluded.';

grant select on public.public_member_profiles to anon, authenticated;

notify pgrst, 'reload schema';
