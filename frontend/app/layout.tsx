import type { Metadata, Viewport } from "next";
import { Host_Grotesk, JetBrains_Mono } from "next/font/google";
import { connection } from "next/server";

import "./globals.css";

/**
 * The document and the fonts, nothing else. The public site and the
 * workspace each supply their own chrome, and each has a `<main id="main">`
 * for the skip link to land on.
 */

const host = Host_Grotesk({
  subsets: ["latin"],
  variable: "--font-host",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

/**
 * Every page renders per request, because the Content-Security-Policy is
 * built around a per-request nonce (`proxy.ts`, `lib/csp.ts`). A prerendered
 * static shell is produced at build time, before any nonce exists, so its
 * inline scripts would carry none and the policy would block them - measured:
 * 46 of 46 scripts un-nonced on `/` before this, all nonced after.
 *
 * `instant = false` on the root layout allows every route to block on the
 * request, and `await connection()` below makes them do so. Cache Components
 * stays on: `<Suspense>` boundaries still stream the data behind skeletons.
 * The cost, stated: no page is served from a prebuilt shell or a CDN.
 */
export const instant = false;

export const metadata: Metadata = {
  title: {
    default: "BhashaBench — test voice AI on how India actually speaks",
    template: "%s · BhashaBench",
  },
  description:
    "Run scripted callers in 13 Indian languages against your voice bot, under codecs, jitter and noise, " +
    "and read back every turn, recording and measured error rate.",
  applicationName: "BhashaBench",
  openGraph: {
    title: "BhashaBench",
    description: "Testing and benchmarking for Indian-language voice AI.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection();
  return (
    <html lang="en" className={`${host.variable} ${jetbrains.variable}`}>
      <body className="min-h-dvh antialiased">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
