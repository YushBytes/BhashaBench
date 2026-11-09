"use client";

import Link from "next/link";
import { useState } from "react";

import { Wordmark } from "@/components/shell/wordmark";
import { buttonClass, cx } from "@/components/ui/primitives";
import { site } from "@/lib/content";

const LINKS = [
  { href: "#workflow", label: "How it works" },
  { href: "#capabilities", label: "Capabilities" },
  { href: "#conditions", label: "Conditions" },
  { href: "#status", label: "Status" },
] as const;

/**
 * The public header.
 *
 * Section links collapse into a real disclosure on small screens rather
 * than disappearing — the Phase 8 audit found the previous header dropping
 * its entire nav below 768px with nothing in its place.
 */
export function SiteHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link
          href="/"
          className="flex min-h-11 items-center rounded-md pr-2 transition-colors"
        >
          <Wordmark />
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-1 lg:flex">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="rounded-md px-3 py-2 text-[13px] text-text-dim transition-colors hover:bg-surface hover:text-text"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          {/* Wrapped rather than given `hidden sm:inline-flex` directly:
              `buttonClass` already sets `inline-flex`, and two display
              utilities of equal specificity are resolved by stylesheet order,
              not by the order they appear in the attribute. The button won,
              the link stayed visible below `sm`, and the header overflowed by
              9px on a 360px screen. */}
          <span className="hidden sm:block">
            <Link href="/app" className={buttonClass("primary", "sm")}>
              Open the workspace
            </Link>
          </span>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls="site-sections"
            className="flex size-11 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface hover:text-text lg:hidden"
          >
            <span className="sr-only">{open ? "Hide" : "Show"} sections</span>
            <svg
              viewBox="0 0 20 20"
              className="size-[18px]"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            >
              {open ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 6h14M3 10h14M3 14h14" />}
            </svg>
          </button>
        </div>
      </div>

      {open ? (
        <div id="site-sections" className="border-t border-line bg-surface lg:hidden">
          <nav aria-label="Sections" className="mx-auto max-w-6xl px-4 py-2 sm:px-6">
            {LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="block rounded-md px-2 py-3 text-[14px] text-text-dim transition-colors hover:bg-surface-raised hover:text-text"
              >
                {link.label}
              </a>
            ))}
            <Link
              href="/app"
              onClick={() => setOpen(false)}
              className={cx(buttonClass("primary", "md"), "mt-2 w-full sm:hidden")}
            >
              Open the workspace
            </Link>
          </nav>
        </div>
      ) : null}
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div>
          <Wordmark subdued />
          <p className="mt-2 max-w-md text-[12px] leading-relaxed text-text-muted">
            An instrument for testing Indian-language voice AI. It reports what
            it measured and names what it did not.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-[13px]">
          <Link href="/app" className="text-text-dim hover:text-text">
            Workspace
          </Link>
          <a
            href={site.repository}
            target="_blank"
            rel="noreferrer"
            className="text-text-dim hover:text-text"
          >
            Source
          </a>
          <a
            href={`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/docs`}
            target="_blank"
            rel="noreferrer"
            className="text-text-dim hover:text-text"
          >
            API reference
          </a>
        </div>
      </div>
    </footer>
  );
}
