-- Rollback for member_auth_close_anon_writes.sql: restore the open anon write
-- policies (as left by the P3 policy files, i.e. `to anon`) and the anon RPC grants.

create policy "member tags are publicly insertable" on public.member_tags for insert to anon with check (true);
create policy "member tags are publicly updatable" on public.member_tags for update to anon using (true) with check (true);
create policy "member tags are publicly deletable" on public.member_tags for delete to anon using (true);
create policy "member links are publicly insertable" on public.member_links for insert to anon with check (true);
create policy "member links are publicly deletable" on public.member_links for delete to anon using (true);
create policy "member profiles self intro is publicly editable" on public.member_profiles for update to anon using (true) with check (true);
create policy "member matching settings are publicly insertable" on public.member_matching_settings for insert to anon with check (true);
create policy "member matching settings are publicly updatable" on public.member_matching_settings for update to anon using (true) with check (true);
create policy "member availability is publicly insertable" on public.member_availability for insert to anon with check (true);
create policy "member availability is publicly deletable" on public.member_availability for delete to anon using (true);
create policy "member availability overrides are publicly insertable" on public.member_availability_overrides for insert to anon with check (true);
create policy "member availability overrides are publicly deletable" on public.member_availability_overrides for delete to anon using (true);
create policy "community posts are publicly deletable" on public.community_posts for delete to anon using (true);
create policy "bookshelf covers are publicly insertable" on storage.objects for insert to anon with check (bucket_id = 'bookshelf-covers');

grant execute on function public.update_member_location_map(text, text, text, text, text, double precision, double precision, double precision, double precision, text) to anon;
grant execute on function public.update_bookshelf_book_thumbnail(uuid, text) to anon;
grant execute on function public.update_member_profile_publication(text, text, boolean) to anon;

create or replace function public.get_member_discord_user_id(p_nickname text)
returns text
language sql
security definer
set search_path = public
stable
as $$
  select discord_user_id
  from public.member_profiles
  where nickname = p_nickname;
$$;

grant execute on function public.get_member_discord_user_id(text) to anon;
