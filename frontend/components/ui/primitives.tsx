/**
 * The shared vocabulary every surface is built from.
 *
 * These are server components unless they need an event handler. Keeping
 * them server-side is why the dashboard ships almost no JavaScript: a badge,
 * a table row and a panel have no behaviour, so they have no reason to cost
 * anything on the client.
 */

import type { ComponentProps, ElementType, ReactNode } from "react";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

type ButtonTone = "primary" | "default" | "quiet" | "danger";
type ButtonSize = "sm" | "md";

const BUTTON_TONES: Record<ButtonTone, string> = {
  // Accent is reserved for the primary action on a surface. Dark text on it,
  // because the accent is light enough that white would not read.
  primary:
    "bg-accent text-bg font-semibold hover:bg-accent-strong active:bg-accent " +
    "disabled:bg-line-strong disabled:text-text-muted",
  default:
    "border border-line-strong bg-surface-raised text-text hover:border-[#3b4756] " +
    "hover:bg-[#1b222c] active:bg-surface disabled:text-text-muted",
  quiet:
    "text-text-dim hover:bg-surface-raised hover:text-text active:bg-surface " +
    "disabled:text-text-muted",
  danger:
    "border border-bad/40 bg-bad-dim text-bad hover:border-bad/70 hover:bg-[#3a1b1f] " +
    "disabled:text-text-muted",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  // 36px and 44px tall. The large size meets the 44px touch target; the
  // small one is for toolbars, where a pointer is the realistic input.
  sm: "h-9 px-3 text-[13px] gap-1.5",
  md: "h-11 px-4 text-sm gap-2",
};

interface ButtonOwnProps {
  tone?: ButtonTone;
  size?: ButtonSize;
  children: ReactNode;
  className?: string;
}

export function buttonClass(
  tone: ButtonTone = "default",
  size: ButtonSize = "md",
  className?: string,
): string {
  return cx(
    "inline-flex items-center justify-center rounded-md whitespace-nowrap",
    "transition-colors duration-[120ms] ease-[cubic-bezier(0.2,0,0,1)]",
    "disabled:cursor-not-allowed disabled:opacity-70",
    BUTTON_TONES[tone],
    BUTTON_SIZES[size],
    className,
  );
}

export function Button({
  tone = "default",
  size = "md",
  className,
  children,
  ...rest
}: ButtonOwnProps & ComponentProps<"button">) {
  return (
    <button className={buttonClass(tone, size, className)} {...rest}>
      {children}
    </button>
  );
}

export function LinkButton({
  tone = "default",
  size = "md",
  className,
  children,
  ...rest
}: ButtonOwnProps & ComponentProps<"a">) {
  return (
    <a className={buttonClass(tone, size, className)} {...rest}>
      {children}
    </a>
  );
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

/**
 * A bordered region.
 *
 * Deliberately not called Card and deliberately not the page's structure:
 * a grid of identical icon-heading-text cards is the lazy scaffold. This is
 * for grouping a table or a labelled set of values, and it never nests.
 */
export function Panel({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: ElementType;
}) {
  return (
    <Tag
      className={cx(
        // `min-w-0` is load-bearing. A grid or flex child defaults to
        // `min-width: auto`, so a panel holding a `min-w-max` table would
        // inflate its own track and push the whole page sideways instead of
        // scrolling inside its own container.
        "min-w-0 rounded-lg border border-line bg-surface",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

export function PanelHeader({
  title,
  description,
  actions,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-line px-4 py-3">
      <div className="min-w-0 flex-1">
        <h2 id={id} className="text-sm font-semibold tracking-tight text-text">
          {title}
        </h2>
        {description ? (
          <p className="mt-1 max-w-prose text-[13px] leading-relaxed text-text-dim">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Labelled values
// ---------------------------------------------------------------------------

/**
 * One fact and its name.
 *
 * `mono` for machine values - ids, seeds, durations, language tags - which
 * are compared character by character. Not for prose.
 */
export function Fact({
  label,
  children,
  mono = false,
  hint,
}: {
  label: ReactNode;
  children: ReactNode;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {label}
      </dt>
      <dd
        className={cx(
          "mt-1 truncate text-[13px] text-text",
          mono && "font-mono tabular",
        )}
        title={hint}
      >
        {children}
      </dd>
    </div>
  );
}

/**
 * A value the backend did not report.
 *
 * A component rather than a string so "not reported" can never drift into
 * a zero, a dash that reads as a measurement, or an empty cell that reads as
 * a bug. `confidence: null` means the provider does not report confidence;
 * rendering 0 or 100% would both be fiction.
 */
export function NotReported({ what }: { what?: string }) {
  return (
    <span
      className="text-text-muted italic"
      title={what ? `${what} is not reported by this provider.` : undefined}
    >
      not reported
    </span>
  );
}

// ---------------------------------------------------------------------------
// States
// ---------------------------------------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("bb-skeleton", className)} aria-hidden="true" />;
}

/** A loading placeholder shaped like the rows it replaces. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  );
}

/**
 * Nothing here yet — and what to do about it.
 *
 * Empty is the default state of a fresh BhashaBench install, not an edge
 * case, so an empty state that only says "no results" wastes the one screen
 * every new operator is guaranteed to see.
 */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-4 py-10 sm:items-center sm:text-center">
      <p className="text-sm font-medium text-text">{title}</p>
      {children ? (
        <p className="max-w-md text-[13px] leading-relaxed text-text-dim">{children}</p>
      ) : null}
      {action}
    </div>
  );
}

/**
 * Something failed, said plainly.
 *
 * Names the problem and the recovery. Never a generic "something went
 * wrong", which tells an operator nothing they did not already know.
 */
export function ErrorState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-4 py-10" role="alert">
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="inline-block size-1.5 rounded-full bg-bad"
        />
        <p className="text-sm font-medium text-bad">{title}</p>
      </div>
      {detail ? (
        <p className="max-w-xl text-[13px] leading-relaxed text-text-dim">{detail}</p>
      ) : null}
      {action}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

/**
 * A wide table scrolls inside its own container.
 *
 * The page body must never scroll horizontally, so every table on every
 * surface goes through this wrapper rather than relying on each page to
 * remember.
 */
export function TableScroll({ children }: { children: ReactNode }) {
  return (
    <div className="w-full max-w-full overflow-x-auto">
      <div className="min-w-max">{children}</div>
    </div>
  );
}

export function Th({
  children,
  className,
  ...rest
}: ComponentProps<"th">) {
  return (
    <th
      scope="col"
      className={cx(
        "whitespace-nowrap px-3 py-2 text-left text-[11px] font-medium",
        "uppercase tracking-[0.08em] text-text-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({ children, className, ...rest }: ComponentProps<"td">) {
  return (
    <td className={cx("px-3 py-2.5 text-[13px] text-text-dim", className)} {...rest}>
      {children}
    </td>
  );
}
