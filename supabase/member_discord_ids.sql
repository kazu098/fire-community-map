-- Member Discord user IDs, for the "相談してみる" consultation-DM-draft
-- feature on the member detail page (client links out to
-- https://discord.com/users/{discord_user_id} to open a DM with that
-- member -- Discord has no way to prefill DM text via URL, so the client
-- only offers a copyable draft plus this link; nothing is auto-sent).
--
-- This reverses the "Does not store Discord user IDs" comment on
-- member_profiles from schema.sql: that was written when nothing in the
-- app needed a Discord user id yet. Kept service-role-write-only (no
-- anon/authenticated UPDATE grant on this column), same treatment as
-- avatar_url, since a member should not be able to set another member's
-- (or their own) Discord id by hand.

alter table public.member_profiles
  add column if not exists discord_user_id text;

comment on table public.member_profiles is
  'Member directory profile data sourced from the member spreadsheet and Discord self-introduction channel.';
comment on column public.member_profiles.discord_user_id is
  'Discord user id, resolved from the guild member list by scripts/sync_member_discord_ids.py (service role only -- not member-editable). Used to link to a DM (https://discord.com/users/{id}) from the consultation-draft feature. Null if the member could not be matched to a guild member.';
