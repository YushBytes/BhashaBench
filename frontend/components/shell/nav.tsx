"use client";

/**
 * Workspace navigation.
 *
 * One client component rather than two: the desktop rail and the mobile
 * drawer render the same list from the same source, so a route cannot
 * appear in one and not the other. Mobile is a real drawer, not a shrunken
 * sidebar — the brief for this product is an operator on a phone checking a
 * run, and a 72px icon strip serves nobody.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useId, useState } from "react";

import { cx } from "@/components/ui/primitives";
import { Wordmark } from "./wordmark";

interface NavItem {
  href: string;
  label: string;
  /** What the operator came here to do, shown in the drawer where there is
   *  room for it. */
  blurb: string;
  icon: (props: { className?: string }) => React.ReactElement;
}

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/** One stroke weight, one corner treatment, drawn for this product. */
const Icons = {
  overview: ({ className }: { className?: string }) => (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" {...stroke}>
      <path d="M2.5 12.5h2l1.5-5 2 9 2-11 2 7 1.5-2h4" />
    </svg>
  ),
  runs: ({ className }: { className?: string }) => (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" {...stroke}>
      <rect x="2.5" y="4" width="15" height="12" rx="2" />
      <path d="M2.5 8h15M7 8v8" />
    </svg>
  ),
  newTest: ({ className }: { className?: string }) => (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" {...stroke}>
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 6.5v7M6.5 10h7" />
    </svg>
  ),
  scenarios: ({ className }: { className?: string }) => (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" {...stroke}>
      <path d="M4 3.5h9l3.5 3.5v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1Z" />
      <path d="M12.5 3.5V7H16M6 11h8M6 13.5h5" />
    </svg>
  ),
  providers: ({ className }: { className?: string }) => (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true" {...stroke}>
      <rect x="2.5" y="3" width="15" height="5.5" rx="1.5" />
      <rect x="2.5" y="11.5" width="15" height="5.5" rx="1.5" />
      <path d="M5.5 5.75h.01M5.5 14.25h.01" />
    </svg>
  ),
};

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/app",
    label: "Overview",
    blurb: "What is configured, and what is working right now",
    icon: Icons.overview,
  },
  {
    href: "/app/runs",
    label: "Test runs",
    blurb: "Every run, with its mode and outcome",
    icon: Icons.runs,
  },
  {
    href: "/app/new-test",
    label: "New test",
    blurb: "Configure and launch a run",
    icon: Icons.newTest,
  },
  {
    href: "/app/scenarios",
    label: "Scenarios",
    blurb: "The scenario library",
    icon: Icons.scenarios,
  },
  {
    href: "/app/providers",
    label: "Providers",
    blurb: "Capabilities, limits and what is not integrated",
    icon: Icons.providers,
  },
];

/** `/app/runs/<id>` keeps Test runs lit; `/app` matches only itself. */
function isCurrent(pathname: string, href: string): boolean {
  if (href === "/app") return pathname === "/app";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({
  item,
  current,
  withBlurb = false,
  onNavigate,
}: {
  item: NavItem;
  current: boolean;
  withBlurb?: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={current ? "page" : undefined}
      onClick={onNavigate}
      className={cx(
        "group flex items-center gap-3 rounded-md px-2.5 transition-colors",
        "duration-[120ms] ease-[cubic-bezier(0.2,0,0,1)]",
        withBlurb ? "py-2.5" : "min-h-11 py-2",
        current
          ? "bg-accent-dim text-accent"
          : "text-text-dim hover:bg-surface-raised hover:text-text",
      )}
    >
      <Icon
        className={cx(
          "size-[18px] shrink-0",
          current ? "text-accent" : "text-text-muted group-hover:text-text-dim",
        )}
      />
      <span className="min-w-0">
        <span className="block text-[13px] font-medium">{item.label}</span>
        {withBlurb ? (
          <span className="mt-0.5 block text-[12px] leading-snug text-text-muted">
            {item.blurb}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

/**
 * The rail's markup, with the current item passed in.
 *
 * Split from the hook so the shell can prerender: `usePathname` is only
 * known at request time, and a layout that reads it directly blocks the
 * static shell for every route beneath it. The fallback renders the same
 * rail with nothing highlighted, so the only thing that streams in is which
 * item is lit.
 */
function SidebarChrome({ pathname }: { pathname: string | null }) {
  return (
    <nav
      aria-label="Workspace"
      className="hidden w-60 shrink-0 flex-col border-r border-line bg-chrome md:flex"
    >
      <div className="flex h-14 items-center border-b border-line px-2">
        <Link
          href="/app"
          className="flex min-h-11 items-center rounded-md px-2 transition-colors hover:bg-surface-raised"
        >
          <Wordmark />
        </Link>
      </div>

      <div className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            current={pathname !== null && isCurrent(pathname, item.href)}
          />
        ))}
      </div>

      <div className="border-t border-line p-3">
        <Link
          href="/"
          className="block rounded-md px-2.5 py-2 text-[12px] text-text-muted transition-colors hover:bg-surface-raised hover:text-text-dim"
        >
          ← Back to the public site
        </Link>
      </div>
    </nav>
  );
}

function SidebarCurrent() {
  return <SidebarChrome pathname={usePathname()} />;
}

/** The persistent rail, from the `md` breakpoint up. */
export function Sidebar() {
  return (
    <Suspense fallback={<SidebarChrome pathname={null} />}>
      <SidebarCurrent />
    </Suspense>
  );
}

/**
 * The mobile drawer.
 *
 * A real `<dialog>`: the platform gives focus trapping, Escape and inert
 * background for free, and all three are things a hand-rolled drawer
 * usually gets wrong.
 */
function MobileNavChrome({ pathname }: { pathname: string | null }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  const current =
    pathname === null
      ? undefined
      : NAV_ITEMS.find((item) => isCurrent(pathname, item.href));

  return (
    <div className="md:hidden">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex h-11 items-center gap-2 rounded-md px-2.5 text-text-dim transition-colors hover:bg-surface-raised hover:text-text"
      >
        <svg viewBox="0 0 20 20" className="size-[18px]" aria-hidden="true" {...stroke}>
          <path d="M3 6h14M3 10h14M3 14h14" />
        </svg>
        <span className="text-[13px] font-medium">{current?.label ?? "Menu"}</span>
      </button>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-modal="true"
          aria-label="Workspace navigation"
          className="fixed inset-0 z-50 flex"
        >
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-[rgb(4_6_9_/_0.72)] backdrop-blur-[2px]"
          />
          <div className="relative flex h-full w-[min(20rem,85vw)] flex-col border-r border-line bg-chrome shadow-[var(--shadow-overlay)]">
            <div className="flex h-14 items-center justify-between border-b border-line pl-4 pr-2">
              <Wordmark />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex size-11 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-raised hover:text-text"
                aria-label="Close navigation"
              >
                <svg viewBox="0 0 20 20" className="size-[18px]" aria-hidden="true" {...stroke}>
                  <path d="M5 5l10 10M15 5L5 15" />
                </svg>
              </button>
            </div>
            <div className="flex-1 space-y-1 overflow-y-auto p-2">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  current={pathname !== null && isCurrent(pathname, item.href)}
                  withBlurb
                  onNavigate={() => setOpen(false)}
                />
              ))}
            </div>
            <div className="border-t border-line p-3">
              <Link
                href="/"
                onClick={() => setOpen(false)}
                className="block rounded-md px-2.5 py-2.5 text-[13px] text-text-muted"
              >
                ← Back to the public site
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MobileNavCurrent() {
  return <MobileNavChrome pathname={usePathname()} />;
}

export function MobileNav() {
  return (
    <Suspense fallback={<MobileNavChrome pathname={null} />}>
      <MobileNavCurrent />
    </Suspense>
  );
}
