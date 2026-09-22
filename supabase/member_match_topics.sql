-- ゆるトーク画面 (共通タグ・会話きっかけ質問・関連ニュース) のためのスナップショット。
-- itチームのDiscordでのmemeto0531さんの提案(2026-09-23、
-- https://discord.com/channels/1389921372683112539/1514597598357491742/1551966298039263232)を反映。
--
-- マッチング告知と同時にmember_match_groups 1件につき1行生成する、表示用の
-- 事前計算済みスナップショット。common_tags には各タグごとの質問・ニュースも
-- まとめて埋め込む(参照時にJOINを増やさずシンプルに1行で読めるようにするため)。
-- 書き込みはscripts/run_member_matching.pyがservice roleキーで行う。
--
-- 閲覧は「URLを知っていればアクセス可能」という方針(かずさんの判断、2026-09-23)。
-- サイト全体がBasic認証の裏にあるため、匿名anonの単純なselect公開で十分としている。

create table if not exists public.member_match_group_topics (
  group_id uuid primary key references public.member_match_groups (id) on delete cascade,
  group_topic text,
  pair_topics jsonb not null default '[]'::jsonb,
  common_tags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

comment on table public.member_match_group_topics is
  'ゆるトーク画面(共通タグ・会話のきっかけ質問・関連ニュース)用の表示スナップショット。member_match_groups 1件につき1行。scripts/run_member_matching.pyがマッチング成立と同時にservice roleキーで書き込む。';
comment on column public.member_match_group_topics.pair_topics is
  '2人組ごとの話題候補。[{"a": "...", "b": "...", "topic": "..."}] の配列(run_member_matching.pyのpairwise_topicsと同じ内容)。';
comment on column public.member_match_group_topics.common_tags is
  'グループ内で2人以上が共有しているタグ。[{"category", "label", "value", "count", "questions": [...], "news": [{"title","url","source","published_at"}]}] の配列。newsは対象カテゴリ(興味・興味あるテーマや話題・投資スタイル・活動/部活)のみ、信頼できる報道系サイトのRSSから取得したキャッシュ(scripts/topic_news.py、14日キャッシュ)。件数はカテゴリを問わず0件のことがある。';

alter table public.member_match_group_topics enable row level security;

drop policy if exists "member match group topics are publicly readable" on public.member_match_group_topics;
create policy "member match group topics are publicly readable"
on public.member_match_group_topics
for select
to anon, authenticated
using (true);

-- ================================================================
-- タグ値ごとのニュース取得キャッシュ (scripts/topic_news.py)
-- ================================================================
-- タグの値(例: "不動産投資")をキーに、直近取得したニュース見出しをまとめて1行に
-- 保持する。マッチングのたびに毎回RSSを叩くと同じタグが短期間に何度も再取得されて
-- 無駄なので、14日以内に取得済みならキャッシュを使い回す(scripts/topic_news.py の
-- NEWS_CACHE_MAX_AGE_DAYS)。ゆるマッチングの開催間隔が概ね1か月以内であることから、
-- 鮮度より「補助的な話のタネ」としての手軽さを優先する判断(かずさん、2026-09-23)。

create table if not exists public.topic_news_cache (
  tag_value text primary key,
  articles jsonb not null default '[]'::jsonb,
  fetched_at timestamptz not null default now()
);

comment on table public.topic_news_cache is
  'タグ値ごとの直近ニュース見出しキャッシュ(最大3件)。scripts/topic_news.pyがGoogleニュースRSSを信頼できる報道系サイト(NHK・日経・Reuters・東洋経済オンライン・ダイヤモンドオンライン)に絞って取得し、service roleキーでupsertする。14日以内のキャッシュがあれば再取得しない。';
comment on column public.topic_news_cache.articles is
  '[{"title": "...", "url": "...", "source": "...", "published_at": "..."}] の配列。該当する記事が見つからなければ空配列。';

alter table public.topic_news_cache enable row level security;

drop policy if exists "topic news cache is publicly readable" on public.topic_news_cache;
create policy "topic news cache is publicly readable"
on public.topic_news_cache
for select
to anon, authenticated
using (true);
