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
