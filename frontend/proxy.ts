/**
 * An optimistic sign-in check for the workspace.
 *
 * Without it, a signed-out visit to `/app` is served the prerendered shell
 * and learns it must sign in only from the streamed content. This redirects
 * at the edge when no session cookie is present at all.
 *
 * It is a convenience, not the control: the cookie's presence is all it
 * checks. Whether the session is valid, and what it may see, is decided by
 * the API on every request, and an expired cookie is caught there
 * (`lib/api/server.ts`).
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (request.cookies.get("bb_session")?.value) return NextResponse.next();
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/app", "/app/:path*"],
};
