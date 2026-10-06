// 相談テーママッチング (GitHub issue #322): post / withdraw a consultation theme.
//
//   POST { action: "create", body: "..." } -> ふぁいにゃ posts the theme anonymously to the
//                                            ゆるマッチング channel and adds a ✋ reaction
//   POST { action: "withdraw", id: "..." } -> deletes that post and closes the theme
//
// Who wrote a theme is never sent to Discord or returned to anyone else: the member is
// identified only from the verified Supabase session (Discord id -> member_profiles), the
// row is written with the service role, and members can read only their own rows (RLS,
// see supabase/consultation_requests.sql). Counting hands and forming the group happen in
// scripts/process_consultation_requests.py.
//
// Only members with ゆるマッチング ON and at least one availability slot can post: hands are
// counted by overlapping availability, and the date poll needs a shared slot.
//
// Secrets: DISCORD_BOT_TOKEN (required, already set for member-onboarding).
// DISCORD_MATCHING_CHANNEL_ID defaults to the #ゆるマッチング channel.

import { createClient } from "npm:@supabase/supabase-js@2";

const DISCORD_API = "https://discord.com/api/v10";
const MATCHING_CHANNEL_ID = Deno.env.get("DISCORD_MATCHING_CHANNEL_ID") ?? "1545300537950470185";
const AUTH_PROVIDER = "custom:discord-id";
const BODY_MIN = 5;
const BODY_MAX = 500;
const RECRUIT_DAYS = 7;
const HAND_EMOJI = "✋";
const WEEKDAY_KANJI = ["日", "月", "火", "水", "木", "金", "土"];

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

async function discord(method: string, path: string, token: string, payload?: unknown): Promise<{ status: number; data: any }> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch(`${DISCORD_API}${path}`, {
      method,
      headers: {
        Authorization: `Bot ${token}`,
        "User-Agent": "fire-community-map-consultation/0.1",
        ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    if (res.status === 429) {
      const body = await res.json().catch(() => ({}));
      await new Promise((r) => setTimeout(r, Math.ceil((body.retry_after ?? 1) * 1000)));
      continue;
    }
    const text = await res.text();
    return { status: res.status, data: text ? JSON.parse(text) : null };
  }
  return { status: 429, data: null };
}

export function normalizeBody(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const body = value
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const length = [...body].length;
  if (length < BODY_MIN || length > BODY_MAX) return null;
  return body;
}

function formatDeadline(deadline: Date): string {
  // JST
  const jst = new Date(deadline.getTime() + 9 * 3600 * 1000);
  return `${jst.getUTCMonth() + 1}/${jst.getUTCDate()}(${WEEKDAY_KANJI[jst.getUTCDay()]})`;
}

export function formatRecruitPost(body: string, deadline: Date): string {
  const quoted = body.split("\n").map((line) => `> ${line}`).join("\n");
  return [
    "🐾 ふぁいにゃです。こんな相談テーマで話したい人がいます（投稿した人は匿名です）。",
    quoted,
    "",
    `話せる方は ${HAND_EMOJI} でリアクションしてください。時間帯が合う方が集まったら、ゆるマッチングとしてご案内します（締め切り: ${formatDeadline(deadline)}）。`,
    "※ゆるマッチングをONにして、空いている時間帯を登録している方が対象です。",
  ].join("\n");
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders(req) });
  if (req.method !== "POST") return json(req, { status: "error", error: "method_not_allowed" }, 405);

  const botToken = Deno.env.get("DISCORD_BOT_TOKEN");
  if (!botToken) return json(req, { status: "error", error: "not_configured" }, 500);

  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  // Who is calling: the Discord id comes only from the verified session.
  const jwt = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const { data: userData, error: userError } = await admin.auth.getUser(jwt);
  if (userError || !userData?.user) return json(req, { status: "error", error: "unauthorized" }, 401);
  const identity = (userData.user.identities ?? []).find((i: any) => i.provider === AUTH_PROVIDER);
  const discordId = String(identity?.identity_data?.sub ?? identity?.id ?? "");
  if (!/^\d{5,25}$/.test(discordId)) return json(req, { status: "error", error: "no_discord_identity" }, 403);

  const { data: member } = await admin
    .from("member_profiles").select("nickname").eq("discord_user_id", discordId).maybeSingle();
  if (!member) return json(req, { status: "error", error: "not_a_member" }, 403);
  const nickname = member.nickname as string;

  let payload: any = {};
  try { payload = await req.json(); } catch (_) { /* empty body */ }

  if (payload?.action === "withdraw") {
    const id = String(payload?.id ?? "");
    const { data: row } = await admin
      .from("consultation_requests").select("id,member_nickname,status,discord_message_id").eq("id", id).maybeSingle();
    if (!row || row.member_nickname !== nickname) return json(req, { status: "not_found" }, 404);
    if (row.status !== "recruiting") return json(req, { status: "already_closed" }, 409);
    if (row.discord_message_id) {
      const { status } = await discord("DELETE", `/channels/${MATCHING_CHANNEL_ID}/messages/${row.discord_message_id}`, botToken);
      if (status !== 204 && status !== 404) return json(req, { status: "error", error: "discord_unavailable" }, 502);
    }
    await admin.from("consultation_requests")
      .update({ status: "withdrawn", closed_at: new Date().toISOString() }).eq("id", id);
    return json(req, { status: "withdrawn" });
  }

  if (payload?.action !== "create") return json(req, { status: "error", error: "unknown_action" }, 400);

  const body = normalizeBody(payload?.body);
  if (!body) return json(req, { status: "invalid_body", min: BODY_MIN, max: BODY_MAX }, 400);

  const [{ data: settings }, { count: slotCount }] = await Promise.all([
    admin.from("member_matching_settings").select("opted_in").eq("member_nickname", nickname).maybeSingle(),
    admin.from("member_availability").select("id", { count: "exact", head: true }).eq("member_nickname", nickname),
  ]);
  if (!settings?.opted_in) return json(req, { status: "not_opted_in" }, 409);
  if (!slotCount) return json(req, { status: "no_availability" }, 409);

  const postedAt = new Date();
  const deadline = new Date(postedAt.getTime() + RECRUIT_DAYS * 24 * 3600 * 1000);
  const { data: inserted, error: insertError } = await admin.from("consultation_requests").insert({
    member_nickname: nickname,
    body,
    posted_at: postedAt.toISOString(),
    deadline_at: deadline.toISOString(),
  }).select("id").single();
  if (insertError || !inserted) return json(req, { status: "error", error: "insert_failed" }, 500);

  // allowed_mentions: none -- the theme is posted verbatim, so an "@everyone" in it must not ping.
  const post = await discord("POST", `/channels/${MATCHING_CHANNEL_ID}/messages`, botToken, {
    content: formatRecruitPost(body, deadline),
    allowed_mentions: { parse: [] },
  });
  if (post.status !== 200 || !post.data?.id) {
    await admin.from("consultation_requests").delete().eq("id", inserted.id);
    return json(req, { status: "error", error: "discord_unavailable" }, 502);
  }
  const messageId = String(post.data.id);
  await admin.from("consultation_requests").update({ discord_message_id: messageId }).eq("id", inserted.id);
  await discord("PUT", `/channels/${MATCHING_CHANNEL_ID}/messages/${messageId}/reactions/${encodeURIComponent(HAND_EMOJI)}/@me`, botToken);

  return json(req, { status: "created", id: inserted.id, deadline_at: deadline.toISOString() });
});
