// Discord userinfo proxy for the Supabase custom OAuth provider `custom:discord-id`
// (GitHub issue #253).
//
// Why this exists: Supabase's built-in Discord provider always requests the
// `email` scope (supabase/auth internal/api/provider/discord.go), and we do not
// want to collect members' email addresses. A Supabase *custom* OAuth2 provider
// lets us request only `identify`, but it reads the user's id from the `sub`
// field of the userinfo response, while Discord's /users/@me returns it as
// `id` -- so pointing the custom provider straight at Discord would leave every
// user with an empty id. This endpoint is configured as that provider's
// UserInfo URL: Supabase calls it server-side with the Discord access token it
// just obtained, and it returns the same user with `id` renamed to `sub`.
//
// It stores nothing, logs nothing, needs no secrets, and fails closed: any
// problem returns an error status so Supabase aborts the sign-in instead of
// creating an identity without a valid Discord id.

export const config = { runtime: 'edge' };

const DISCORD_ME_URL = 'https://discord.com/api/users/@me';
const DISCORD_ID_PATTERN = /^\d{5,25}$/;

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

export default async function handler(request) {
  if (request.method !== 'GET') return json({ error: 'method_not_allowed' }, 405);

  const authorization = request.headers.get('authorization') || '';
  if (!/^Bearer \S+$/i.test(authorization)) return json({ error: 'unauthorized' }, 401);

  let res;
  try {
    res = await fetch(DISCORD_ME_URL, { headers: { Authorization: authorization } });
  } catch (e) {
    return json({ error: 'upstream_unreachable' }, 502);
  }
  if (!res.ok) return json({ error: 'upstream_error' }, res.status === 401 ? 401 : 502);

  let user = null;
  try { user = await res.json(); } catch (e) {}
  const id = user && typeof user.id === 'string' ? user.id : '';
  if (!DISCORD_ID_PATTERN.test(id)) return json({ error: 'invalid_user' }, 502);

  const username = typeof user.username === 'string' ? user.username : '';
  const name = typeof user.global_name === 'string' && user.global_name ? user.global_name : username;
  const picture = typeof user.avatar === 'string' && user.avatar
    ? `https://cdn.discordapp.com/avatars/${id}/${user.avatar}.png`
    : '';

  return json({ sub: id, name, preferred_username: username, picture }, 200);
}
