import type { Metadata, Viewport } from "next";
import { Host_Grotesk, JetBrains_Mono } from "next/font/google";

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
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
