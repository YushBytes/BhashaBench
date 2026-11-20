import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "@/components/ui/primitives";

export interface Crumb {
  href?: string;
  label: string;
}

/**
 * The top of every workspace page: breadcrumbs, the title, one line that
 * says what the page is for, and the page's own actions. Prerendered: it
 * takes no request data, so it shows before anything streams in.
 */
export function PageHeader({
  title,
  description,
  actions,
  crumbs,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  crumbs?: Crumb[];
  meta?: ReactNode;
}) {
  return (
    <div className="border-b border-line bg-bg">
      <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
        {crumbs && crumbs.length > 0 ? (
          <nav aria-label="Breadcrumb" className="mb-2.5">
            <ol className="flex flex-wrap items-center gap-1 text-[13px] text-text-3">
              {crumbs.map((crumb, index) => (
                <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
                  {index > 0 ? <ChevronRight aria-hidden="true" className="size-3.5" /> : null}
                  {crumb.href ? (
                    <Link href={crumb.href} className="rounded hover:text-text">
                      {crumb.label}
                    </Link>
                  ) : (
                    <span aria-current="page" className="text-text-2">
                      {crumb.label}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        ) : null}
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <h1 className="break-words text-[24px] font-semibold leading-tight tracking-[-0.03em] text-text sm:text-[26px]">
              {title}
            </h1>
            {description ? <div className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-text-3">{description}</div> : null}
            {meta ? <div className="mt-3 flex flex-wrap items-center gap-2">{meta}</div> : null}
          </div>
          {actions ? <div className="no-print flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      </div>
    </div>
  );
}

export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <main id="main" className={cx("mx-auto w-full min-w-0 max-w-7xl flex-1 space-y-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8", className)}>
      {children}
    </main>
  );
}
