/**
 * The session, for server components. Calls no route itself.
 *
 * A server component's `fetch` goes from the Next server to the backend, so
 * the browser's cookie does not travel by itself: this reads `bb_session`
 * from the incoming request and hands it to `request()` in `client.ts` as a
 * header. The token is only ever forwarded, never logged or rendered.
 *
 * `cookies()` is request-time data, so every caller sits inside a
 * `<Suspense>` boundary - which the workspace pages already require.
 */

import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiError } from "./client";

const SESSION_COOKIE = "bb_session";

/** Headers carrying the session, or a redirect to sign-in when there is none. */
export async function sessionHeaders(): Promise<Record<string, string>> {
  const store = await cookies();
  const session = store.get(SESSION_COOKIE);
  if (!session?.value) redirect("/login");
  return { cookie: `${SESSION_COOKIE}=${session.value}` };
}

/**
 * Call inside a page's `catch`: a 401 means the session expired or was
 * revoked, which is "sign in again", not an error state to render.
 */
export function signInAgainIfExpired(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1");
}
