-- Add external publication settings for member profiles.
-- Apply this once to the Supabase database before using the public toggles.

alter table public.member_profiles add column if not exists nickname_public boolean not null default false;
alter table public.member_profiles add column if not exists avatar_public boolean not null default false;
alter table public.member_profiles add column if not exists external_self_intro_text text;
alter table public.member_profiles add column if not exists self_intro_public boolean not null default false;
alter table public.member_profiles add column if not exists location_public boolean not null default false;
alter table public.member_profiles add column if not exists links_public boolean not null default false;

update public.member_profiles
set external_self_intro_text = self_intro_text
where external_self_intro_text is null
  and self_intro_text is not null;

comment on column public.member_profiles.nickname_public is
  'When true, nickname may be shown on the external public profile directory.';
comment on column public.member_profiles.avatar_public is
  'When true, avatar_url may be shown on the external public profile directory.';
comment on column public.member_profiles.external_self_intro_text is
  'External-facing self-introduction text. Seeded from self_intro_text but edited separately from the internal member profile text.';
comment on column public.member_profiles.self_intro_public is
  'When true, external_self_intro_text may be shown on the external public profile directory.';
comment on column public.member_profiles.location_public is
  'When true, location_text may be shown on the external public profile directory.';
comment on column public.member_profiles.links_public is
  'When true, non-memo member_links may be shown on the external public profile directory.';

grant update (
  nickname_public,
  avatar_public,
  external_self_intro_text,
  self_intro_public,
  location_public,
  links_public
) on public.member_profiles to anon, authenticated;

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

alter table public.member_profile_edits add column if not exists old_external_self_intro_text text;
alter table public.member_profile_edits add column if not exists new_external_self_intro_text text;

create or replace function public.log_member_profile_edit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.self_intro_text is distinct from old.self_intro_text then
    insert into public.member_profile_edits (member_nickname, old_self_intro_text, new_self_intro_text)
    values (new.nickname, old.self_intro_text, new.self_intro_text);
  end if;
  if new.external_self_intro_text is distinct from old.external_self_intro_text then
    insert into public.member_profile_edits (member_nickname, old_external_self_intro_text, new_external_self_intro_text)
    values (new.nickname, old.external_self_intro_text, new.external_self_intro_text);
  end if;
  if new.location_text is distinct from old.location_text then
    insert into public.member_profile_edits (member_nickname, old_location_text, new_location_text)
    values (new.nickname, old.location_text, new.location_text);
  end if;
  return new;
end;
$$;

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
  case when p.self_intro_public then p.external_self_intro_text else null end as display_self_intro_text,
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
