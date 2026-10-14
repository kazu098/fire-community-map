-- ゆるマッチングの話題づくり用: メンバーの「最近の興味」(2026-10-14追加)。
-- scripts/sync_member_interest_signals.py が1日1回、ゆるマッチング参加中のメンバーについて
-- Discordの公開チャンネルの直近30日の投稿と、noteの直近60日の記事(公開RSS)をキーワードで
-- テーマに寄せて数え、1人1行でupsertする。LLM APIは使わない。
-- マッチングのたびにクローリングすると重いので、ここに結果を貯めておき、
-- scripts/run_member_matching.py は読むだけにする。
--
-- Discordの投稿本文は保存しない(テーマ別の件数だけ)。noteの記事タイトルは公開情報なので
-- 直近5件まで持つ。メンバー本人の画面には出さない内部用データなので、RLSを有効にして
-- ポリシーを作らない(=service roleのみ読み書き可、anon/authenticatedは不可)。

create table if not exists public.member_interest_signals (
  member_nickname text primary key,
  recent_themes jsonb not null default '[]'::jsonb,
  theme_counts jsonb not null default '{}'::jsonb,
  recent_note_titles jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

comment on table public.member_interest_signals is
  'ゆるマッチングの話題づくり用の「最近の興味」。scripts/sync_member_interest_signals.pyがDiscord(直近30日)とnote(直近60日)から1日1回集計する。service roleのみ。';
comment on column public.member_interest_signals.recent_themes is
  '最近の投稿から判定したテーマのkey(scripts/yuru_talk_group_topics.pyのTHEMES)。件数の多い順に最大3個。';
comment on column public.member_interest_signals.theme_counts is
  '{"travel": {"discord": 12, "note": 1}, ...} テーマ別の件数。Discordはチャンネル自体のテーマ+本文のキーワード、noteはタイトル+抜粋のキーワード。';
comment on column public.member_interest_signals.recent_note_titles is
  '[{"title": "...", "published_at": "..."}] noteの直近の記事タイトル(最大5件)。';

alter table public.member_interest_signals enable row level security;
