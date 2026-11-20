import type { NextConfig } from "next";

/**
 * The backend, as the Next server reaches it. The browser never calls it
 * directly: `/api/v1/*` on this origin is proxied there, which is what makes
 * the API's HttpOnly, SameSite=Strict session cookie first-party. The API's
 * CORS_ORIGINS must list this site's origin, because the API checks the
 * Origin of every cookie-authenticated write against it.
 */
const BACKEND_URL = (
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  // The API's own hardening headers, for the pages. No Content-Security-
  // Policy yet: Next's inline bootstrap scripts need per-request nonces to be
  // allowed safely, and a policy with 'unsafe-inline' would only look like
  // protection. Recorded as a gap in docs/SECURITY.md.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
  // Routes renamed by the 2026-11 frontend; old links and bookmarks keep working.
  async redirects() {
    return [
      { source: "/app/new-test", destination: "/app/runs/new", permanent: true },
      { source: "/app/providers", destination: "/app/bots", permanent: true },
      { source: "/app/workspace", destination: "/app/settings/team", permanent: true },
    ];
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` }];
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
