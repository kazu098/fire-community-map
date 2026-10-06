// Member onboarding on first Discord login (GitHub issue #253).
//
// The site is members-only: a signed-in user is a member when their Discord
// user id (auth.identities, provider `custom:discord-id`) is linked to a
// member_profiles row. Registration used to go through a Google Form whose
// rows were then matched to Discord by display name (unreliable, and up to a
// day late). Instead, someone who signs in with Discord and has no profile yet
// gets one created from their own Discord data, after confirming it:
//
//   POST { action: "preview" }  -> what the profile would look like, plus tag
//                                  choices and rule-based tag suggestions
//   POST { action: "create", nickname: "...", tags: [{ category, value }] } -> create it
//
// Tag suggestions are rule-based only (no paid API): existing tag phrases used by
// at least two other members that appear in the self-introduction, keyword rules
// for FIRE status, and an MBTI pattern. The member reviews them on the
// confirmation screen, so they replace the old manual tag review.
//
// Only members of the FIRE研究所 Discord server qualify (checked with the bot
// token). The Discord id always comes from the verified Supabase session, never
// from the request body, so nobody can create a profile for someone else.
// The self-introduction is looked up by message author id in the intro channel,
// so it is never mismatched by display name.
//
// Secrets: DISCORD_BOT_TOKEN (required). DISCORD_GUILD_ID and
// DISCORD_INTRO_CHANNEL_ID default to the FIRE研究所 server / 自己紹介 channel.
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are provided by the platform.

import { createClient } from "npm:@supabase/supabase-js@2";

const DISCORD_API = "https://discord.com/api/v10";
const GUILD_ID = Deno.env.get("DISCORD_GUILD_ID") ?? "1389921372683112539";
const INTRO_CHANNEL_ID = Deno.env.get("DISCORD_INTRO_CHANNEL_ID") ?? "1389923387887063171";
const AUTH_PROVIDER = "custom:discord-id";
const MAX_INTRO_PAGES = 20; // 100 messages per page
const NICKNAME_MAX = 40;
const TAG_VALUE_MAX = 30;
const TAGS_MAX = 40;
const TAG_CATEGORIES = new Set([
  "investment_style", "fire_status", "mbti", "skill", "consultation", "wants_to_know", "interest", "chat_topic", "affiliation",
]);
// Categories offered on the confirmation screen, and how many popular values to show for each.
const ONBOARDING_TAG_OPTIONS: Record<string, number> = {
  fire_status: 10, investment_style: 14, mbti: 17, interest: 16, skill: 12, consultation: 10, wants_to_know: 10,
};
const SUGGESTION_MIN_USERS = 2; // ignore phrases only one member uses
const FIRE_RULES: Array<[RegExp, string]> = [ // matched against normalized text; first match wins
  [/サイドfire(済|達成|しました|中です|してい)/, "サイドFIRE"],
  [/サイドfire(を?目指|準備|予定|検討)/, "サイドFIRE目指し中"],
  [/バリスタfire(済|達成|しました)/, "バリスタFIRE"],
  [/バリスタfire/, "バリスタFIRE目指し中"],
  [/コーストfire/, "コーストFIRE"],
  [/(fire|ファイア)(済|達成|しました|してい|後)/, "FIRE済"],
  [/(fire|ファイア)(を?目指|準備|予定|まで)/, "FIRE目指し中"],
  [/サイドfire/, "サイドFIRE"],
];
const MBTI_PATTERN = /(?<![A-Za-z])([IE][NS][TF][JP])(?:\s*[-ー‐–]?\s*([AT]))?(?![A-Za-z])/;
const PREFECTURES = [
  "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県",
  "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
  "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県",
  "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
];

const ALLOWED_ORIGINS = new Set([
  "https://fire-community-map.vercel.app",
  "http://localhost:8000",
]);

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin) ? origin : "https://fire-community-map.vercel.app",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

function json(req: Request, body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(req), "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

async function discordGet(path: string, token: string): Promise<{ status: number; data: any }> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch(`${DISCORD_API}${path}`, {
      headers: { Authorization: `Bot ${token}`, "User-Agent": "fire-community-map-onboarding/0.1" },
    });
    if (res.status === 429) {
      const body = await res.json().catch(() => ({}));
      await new Promise((r) => setTimeout(r, Math.ceil((body.retry_after ?? 1) * 1000)));
      continue;
    }
    const data = res.ok ? await res.json() : null;
    return { status: res.status, data };
  }
  return { status: 429, data: null };
}

// Same markers / nickname rule as scripts/fetch_self_intros.py.
const SELF_INTRO_MARKERS = ["【ニックネーム】", "【属性】", "【年齢", "【現在の仕事", "【投資"];

function isSelfIntro(message: any): boolean {
  const content = String(message?.content ?? "").trim();
  const hits = SELF_INTRO_MARKERS.filter((m) => content.includes(m)).length;
  if (hits >= 2) return true;
  return content.includes("自己紹介") && Array.isArray(message?.attachments) && message.attachments.length > 0;
}

function declaredNickname(content: string): string | null {
  const match = content.match(/【ニックネーム】\s*\n?\s*(?:→\s*)?(.+)/);
  if (!match) return null;
  // 「のこ　Note: https://…」のように後ろに続く補足は、全角スペースか2つ以上の空白で切る。
  const value = match[1].trim().split(/　|\s{2,}/)[0].replace(/[です。、,.!！ 　]+$/u, "");
  return value || null;
}

async function findLatestSelfIntro(token: string, discordId: string): Promise<any | null> {
  let before: string | null = null;
  for (let page = 0; page < MAX_INTRO_PAGES; page++) {
    const query = `limit=100${before ? `&before=${before}` : ""}`;
    const { status, data } = await discordGet(`/channels/${INTRO_CHANNEL_ID}/messages?${query}`, token);
    if (status !== 200 || !Array.isArray(data) || data.length === 0) return null;
    // Messages come newest first, so the first match is the latest self-intro.
    const hit = data.find((m: any) => m?.author?.id === discordId && isSelfIntro(m));
    if (hit) return hit;
    if (data.length < 100) return null;
    before = data[data.length - 1].id;
  }
  return null;
}

function avatarUrl(member: any, discordId: string): string | null {
  if (member?.avatar) return `https://cdn.discordapp.com/guilds/${GUILD_ID}/users/${discordId}/avatars/${member.avatar}.png?size=256`;
  if (member?.user?.avatar) return `https://cdn.discordapp.com/avatars/${discordId}/${member.user.avatar}.png?size=256`;
  return null;
}

function normalizeText(value: string): string {
  return value.normalize("NFKC").replace(/\s+/g, "").toLowerCase();
}

type Tag = { category: string; value: string };

async function loadAllTags(admin: any): Promise<Tag[]> {
  const rows: Tag[] = [];
  for (let from = 0; ; from += 1000) {
    const { data, error } = await admin.from("member_tags").select("category,value").range(from, from + 999);
    if (error || !data) break;
    rows.push(...data);
    if (data.length < 1000) break;
  }
  return rows;
}

// Popular values per category (for the choice buttons) and rule-based suggestions.
function buildTagChoices(allTags: Tag[], introText: string | null) {
  const counts = new Map<string, number>(); // "category\tvalue" -> members using it
  for (const t of allTags) {
    const key = `${t.category}\t${t.value}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const options: Record<string, string[]> = {};
  for (const [category, limit] of Object.entries(ONBOARDING_TAG_OPTIONS)) {
    options[category] = [...counts.entries()]
      .filter(([key]) => key.startsWith(`${category}\t`))
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([key]) => key.split("\t")[1]);
  }

  const suggested: Tag[] = [];
  if (introText) {
    const text = normalizeText(introText);
    // Existing phrases (used by >= 2 members) that appear in the intro. Within a
    // category, when one match contains another, keep the more popular one.
    const hits = [...counts.entries()]
      .map(([key, n]) => ({ category: key.split("\t")[0], value: key.split("\t")[1], n }))
      .filter((t) => t.category !== "mbti" && t.category !== "fire_status" && TAG_CATEGORIES.has(t.category))
      .filter((t) => t.n >= SUGGESTION_MIN_USERS && normalizeText(t.value).length >= 2 && text.includes(normalizeText(t.value)));
    const kept = hits.filter((t) => !hits.some((o) =>
      o !== t && o.category === t.category && normalizeText(o.value).includes(normalizeText(t.value)) && o.n >= t.n));
    suggested.push(...kept.map(({ category, value }) => ({ category, value })));

    const mbti = introText.normalize("NFKC").match(MBTI_PATTERN);
    if (mbti) suggested.push({ category: "mbti", value: mbti[1].toUpperCase() + (mbti[2] ? `-${mbti[2].toUpperCase()}` : "") });
    const fire = FIRE_RULES.find(([pattern]) => pattern.test(text));
    if (fire) suggested.push({ category: "fire_status", value: fire[1] });
    else if (/会社員|勤務|サラリーマン/.test(text)) suggested.push({ category: "fire_status", value: "会社員" });
  }
  return { options, suggested };
}

// The prefecture written on the 居住地 line of the intro template, if any.
function suggestedLocation(introText: string | null): string | null {
  if (!introText) return null;
  const line = introText.split("\n").findIndex((l) => l.includes("居住地"));
  if (line < 0) return null;
  const nearby = introText.split("\n").slice(line, line + 3).join(" ");
  return PREFECTURES.find((p) => nearby.includes(p) || nearby.includes(p.replace(/[都府県]$/, ""))) ?? null;
}

function normalizeTags(value: unknown): Tag[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const tags: Tag[] = [];
  for (const item of value) {
    const category = String(item?.category ?? "");
    const tagValue = String(item?.value ?? "").replace(/[\u0000-\u001f\u007f]/g, "").trim();
    if (!TAG_CATEGORIES.has(category) || !tagValue || [...tagValue].length > TAG_VALUE_MAX) continue;
    const key = `${category}\t${tagValue}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tags.push({ category, value: tagValue });
    if (tags.length >= TAGS_MAX) break;
  }
  return tags;
}

// ilike without wildcards: an exact, case-insensitive nickname match.
function ilikeExact(value: string): string {
  return value.replace(/[\\%_]/g, (c) => `\\${c}`);
}

function normalizeNickname(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const nickname = value.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  if (!nickname || [...nickname].length > NICKNAME_MAX) return null;
  return nickname;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(req) });
  if (req.method !== "POST") return json(req, { status: "error", error: "method_not_allowed" }, 405);

  const botToken = Deno.env.get("DISCORD_BOT_TOKEN");
  if (!botToken) return json(req, { status: "error", error: "not_configured" }, 500);

  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // 1. Who is calling: the Discord id comes only from the verified session.
  const jwt = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const { data: userData, error: userError } = await admin.auth.getUser(jwt);
  if (userError || !userData?.user) return json(req, { status: "error", error: "unauthorized" }, 401);
  const identity = (userData.user.identities ?? []).find((i: any) => i.provider === AUTH_PROVIDER);
  const discordId = String(identity?.identity_data?.sub ?? identity?.id ?? "");
  if (!/^\d{5,25}$/.test(discordId)) return json(req, { status: "error", error: "no_discord_identity" }, 403);

  let body: any = {};
  try { body = await req.json(); } catch (_) { /* empty body */ }
  const action = body?.action === "create" ? "create" : "preview";

  // 2. Already a member? Nothing to create.
  const { data: existing } = await admin
    .from("member_profiles").select("nickname").eq("discord_user_id", discordId).maybeSingle();

  // 3. Must be in the FIRE研究所 Discord server.
  const { status: memberStatus, data: guildMember } = await discordGet(`/guilds/${GUILD_ID}/members/${discordId}`, botToken);
  if (memberStatus === 404 || (memberStatus === 200 && guildMember?.user?.bot)) {
    return json(req, { status: "not_in_guild" });
  }
  if (memberStatus !== 200 || !guildMember) return json(req, { status: "error", error: "discord_unavailable" }, 502);

  // 4. Build the profile from the member's own Discord data.
  const intro = await findLatestSelfIntro(botToken, discordId);
  const introText = intro ? String(intro.content ?? "").trim() || null : null;
  const suggestedNickname = normalizeNickname(
    (introText && declaredNickname(introText)) || guildMember.nick || guildMember.user?.global_name || guildMember.user?.username,
  );
  const profile = {
    avatar_url: avatarUrl(guildMember, discordId),
    self_intro_text: introText,
    self_intro_url: intro ? `https://discord.com/channels/${GUILD_ID}/${INTRO_CHANNEL_ID}/${intro.id}` : null,
    self_intro_posted_at: intro?.timestamp ?? null,
  };

  if (action === "preview") {
    let nicknameTaken = false;
    if (suggestedNickname) {
      const { data: taken } = await admin.from("member_profiles").select("nickname").ilike("nickname", ilikeExact(suggestedNickname)).limit(1);
      nicknameTaken = Boolean(taken && taken.length && !existing);
    }
    const { options, suggested } = buildTagChoices(await loadAllTags(admin), introText);
    return json(req, {
      status: existing ? "linked" : "preview",
      linked_nickname: existing?.nickname ?? null,
      nickname: suggestedNickname,
      nickname_taken: nicknameTaken,
      tag_options: options,
      suggested_tags: suggested,
      suggested_location: suggestedLocation(introText),
      ...profile,
    });
  }

  // action === "create"
  if (existing) return json(req, { status: "linked", linked_nickname: existing.nickname });
  const nickname = normalizeNickname(body?.nickname);
  if (!nickname) return json(req, { status: "invalid_nickname" }, 400);
  const { data: taken } = await admin.from("member_profiles").select("nickname").ilike("nickname", ilikeExact(nickname)).limit(1);
  if (taken && taken.length) return json(req, { status: "nickname_taken" }, 409);

  const { error: insertError } = await admin.from("member_profiles").insert({
    nickname,
    discord_user_id: discordId,
    ...profile,
  });
  if (insertError) {
    if (insertError.code === "23505") {
      // Unique violation: either the nickname, or this Discord id was linked by a concurrent request.
      if (String(insertError.message ?? "").includes("discord_user_id")) return json(req, { status: "linked", linked_nickname: null });
      return json(req, { status: "nickname_taken" }, 409);
    }
    return json(req, { status: "error", error: "insert_failed" }, 500);
  }

  const tags = normalizeTags(body?.tags);
  let tagsSaved = true;
  if (tags.length) {
    const perCategory = new Map<string, number>();
    const rows = tags.map((t) => {
      const order = perCategory.get(t.category) ?? 0;
      perCategory.set(t.category, order + 1);
      return { member_nickname: nickname, category: t.category, value: t.value, sort_order: order };
    });
    const { error: tagError } = await admin.from("member_tags").insert(rows);
    tagsSaved = !tagError;
  }
  return json(req, { status: "created", nickname, tags_saved: tagsSaved });
});
