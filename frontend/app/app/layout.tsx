import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { MobileNav, Sidebar } from "@/components/shell/nav";
import { Wordmark } from "@/components/shell/wordmark";

export const metadata: Metadata = {
  title: { default: "Workspace", template: "%s · BhashaBench" },
};

/**
 * The workspace shell.
 *
 * A fixed rail and a scrolling content column, rather than one long page:
 * an operator moves between a run and the scenario that produced it
 * constantly, and navigation that scrolls away costs a scroll every time.
 *
 * The skip link is first in the DOM. With a persistent sidebar, a keyboard
 * user otherwise tabs through five navigation links on every single page
 * before reaching the content.
 */
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh bg-bg">
      <a
        href="#workspace-content"
        className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-semibold text-bg focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60]"
      >
        Skip to content
      </a>

      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile only. On desktop the rail is the persistent chrome, so a
            second bar would cost 56px of vertical space to repeat a button
            the page header already carries. */}
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-chrome/95 px-3 backdrop-blur-md md:hidden">
          <MobileNav />
          <Link href="/app" className="flex min-h-11 items-center rounded-md px-1">
            <Wordmark />
          </Link>
        </header>

        <main id="workspace-content" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
