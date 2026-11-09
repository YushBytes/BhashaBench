import type { ReactNode } from "react";

/**
 * The heading block every workspace page opens with.
 *
 * No eyebrow above the title. A kicker adds a line of chrome and no
 * information — the heading carries its own weight, and in a dense operator
 * UI the vertical space is worth more than the label.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
}) {
  return (
    <div className="border-b border-line bg-surface-inset">
      <div className="mx-auto max-w-[88rem] px-4 py-5 sm:px-6 sm:py-6">
        {breadcrumb ? <div className="mb-2">{breadcrumb}</div> : null}
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-text sm:text-[22px]">
              {title}
            </h1>
            {description ? (
              <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-text-dim">
                {description}
              </p>
            ) : null}
          </div>
          {actions ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** The content column every workspace page uses, so gutters never disagree. */
export function PageBody({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto max-w-[88rem] space-y-5 px-4 py-5 sm:px-6 sm:py-6">
      {children}
    </div>
  );
}
