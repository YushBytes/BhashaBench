/**
 * Runs before every page: mints the CSP nonce, and checks for a session on
 * the workspace.
 *
 * **CSP.** A fresh 128-bit nonce per request goes into the
 * `Content-Security-Policy` header of both the request (Next reads it there
 * and stamps it on every script and style it renders) and the response (the
 * browser enforces it). The policy itself is `lib/csp.ts`.
 *
 * **Sign-in.** An optimistic check, not the control: a signed-out visit to
 * `/app` is redirected at the edge when no session cookie is present at all.
 * Whether the session is valid, and what it may see, is decided by the API
 * on every request, and an expired cookie is caught there
 * (`lib/api/server.ts`).
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { contentSecurityPolicy, newNonce } from "./lib/csp";

export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if ((path === "/app" || path.startsWith("/app/")) && !request.cookies.get("bb_session")?.value) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", path);
    return NextResponse.redirect(login);
  }

  const nonce = newNonce();
  const policy = contentSecurityPolicy(nonce, { dev: process.env.NODE_ENV === "development" });
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: not the proxied API (the backend sends its own, stricter
      // policy), not static assets, and not link prefetches.
      source: "/((?!api/|_next/static|_next/image|favicon.ico|icon|apple-icon).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
