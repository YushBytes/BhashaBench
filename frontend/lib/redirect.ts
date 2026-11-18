/**
 * Where to go after signing in. Only workspace paths on this site are
 * followed: an open redirect would let a crafted link send a freshly
 * signed-in user anywhere. `//evil.example` is protocol-relative, so it is
 * refused even though it starts with a slash, and so is a backslash variant
 * some browsers normalise into one.
 */
export function safeNext(value: string | null | undefined): string {
  if (!value) return "/app";
  if (value.startsWith("//") || value.includes("\\")) return "/app";
  return value === "/app" || value.startsWith("/app/") || value.startsWith("/app?") ? value : "/app";
}
