export const config = {
  matcher: ['/'],
};

export default function middleware(request) {
  const user = process.env.BASIC_AUTH_USER;
  const pass = process.env.BASIC_AUTH_PASSWORD;

  if (!user || !pass) {
    return new Response('Basic auth is not configured (missing BASIC_AUTH_USER/BASIC_AUTH_PASSWORD).', {
      status: 500,
    });
  }

  const authHeader = request.headers.get('authorization');
  if (authHeader?.startsWith('Basic ')) {
    const decoded = atob(authHeader.slice('Basic '.length));
    const separatorIndex = decoded.indexOf(':');
    const suppliedUser = decoded.slice(0, separatorIndex);
    const suppliedPass = decoded.slice(separatorIndex + 1);
    if (suppliedUser === user && suppliedPass === pass) {
      return;
    }
  }

  return new Response('Authentication required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="FIRE Community Map"' },
  });
}
