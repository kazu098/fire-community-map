-- ゆるマッチングの「🎤 この人に聞いてみたい」(2026-10-14追加)。
-- キーワード判定だけだと話題が「発信・執筆」のような大きなくくりになり具体性が出ないため、
-- メンバーごとに「この人にこれを聞いてみたい」という一言を人の目で用意しておく。
-- LLM APIは使わない(従量課金を避ける、かずさんの判断)。月1回ほど、Claude Code(サブスクの
-- 範囲内)で参加メンバーの最近のnote・Discordの投稿を読んで下書きし、かずさんのレビュー後に
-- scripts/load_conversation_hooks.py でupsertする。結婚・病気・休職などの踏み込んだ話題や、
-- 所属チームの話(内輪ネタになる)は書かない。
--
-- マッチング側(scripts/run_member_matching.py)は読むだけで、更新から HOOK_MAX_AGE_DAYS を
-- 過ぎたものは古いとみなして使わない。内部用データなのでRLSを有効にしてポリシーを作らない
-- (service roleのみ)。告知に載った一言は member_match_group_topics.member_hooks に残る。

create table if not exists public.member_conversation_hooks (
  member_nickname text primary key,
  hooks jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

comment on table public.member_conversation_hooks is
  'ゆるマッチングの「この人に聞いてみたい」。Claude Codeで下書き→レビュー→scripts/load_conversation_hooks.pyでupsert。service roleのみ。';
comment on column public.member_conversation_hooks.hooks is
  '[{"text": "こどもNISAの積立方針、どうやって決めた？", "basis": "note「【こどもNISA】積立方針メモ」(2026-10-12)"}] の配列。basisはレビュー用の根拠で、告知には出さない。';

alter table public.member_conversation_hooks enable row level security;

alter table public.member_match_group_topics
  add column if not exists member_hooks jsonb not null default '[]'::jsonb;

comment on column public.member_match_group_topics.member_hooks is
  'このグループの告知に載せた「この人に聞いてみたい」。[{"nickname": "...", "text": "..."}](member_conversation_hooksから1人1つ選んだもの)。';
