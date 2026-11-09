import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { site } from "@/lib/content";

import "./globals.css";

/**
 * Two fonts, both loaded through `next/font` so they are self-hosted and
 * subset at build time: no render-blocking request to a third party, and no
 * layout shift when they arrive.
 */
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: `${site.name} — ${site.tagline}`,
    template: `%s · ${site.name}`,
  },
  description: site.description,
  applicationName: site.name,
};

/**
 * The root layout carries the document and nothing else.
 *
 * The public site and the workspace have different chrome — a marketing
 * header against a persistent operator rail — so neither belongs here.
 * Each supplies its own.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-bg">{children}</body>
    </html>
  );
}
