/**
 * The primitives every screen is built from. Server-safe: no state, no
 * effects. Interactive pieces live in `interactive.tsx`.
 *
 * One button family, one panel style, one radius scale, one table, one way
 * of saying "not reported". A screen that needs something else adds it here
 * rather than inlining a near-copy.
 */

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { AlertTriangle, CircleSlash, Inbox } from "lucide-react";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// -- Buttons -----------------------------------------------------------------

export type ButtonTone = "primary" | "secondary" | "ghost" | "danger" | "ink";
export type ButtonSize = "sm" | "md" | "lg";

const TONE: Record<ButtonTone, string> = {
  primary:
    "bg-accent text-white shadow-1 hover:bg-accent-hover active:translate-y-px disabled:bg-accent/45",
  ink: "bg-text text-bg shadow-1 hover:bg-[#262628] active:translate-y-px disabled:bg-text/40",
  secondary:
    "border border-line-strong bg-bg text-text shadow-1 hover:border-text-3 hover:bg-bg-soft active:translate-y-px disabled:text-text-3",
  ghost: "text-text-2 hover:bg-bg-sunk hover:text-text active:translate-y-px disabled:text-text-3",
  danger:
    "border border-bad/30 bg-bad-soft text-bad hover:border-bad/60 hover:bg-[#fbe3e3] active:translate-y-px disabled:opacity-50",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-[13px]",
  md: "h-9 gap-2 px-3.5 text-[14px]",
  lg: "h-11 gap-2 px-5 text-[15px]",
};

export function buttonClass(
  tone: ButtonTone = "secondary",
  size: ButtonSize = "md",
  extra?: string,
): string {
  return cx(
    "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-md font-medium",
    "transition-[background-color,border-color,color,transform] duration-150",
    "disabled:cursor-not-allowed disabled:translate-y-0",
    TONE[tone],
    SIZE[size],
    extra,
  );
}

export function Button({
  tone = "secondary",
  size = "md",
  className,
  type = "button",
  ...rest
}: ComponentProps<"button"> & { tone?: ButtonTone; size?: ButtonSize }) {
  return <button type={type} className={buttonClass(tone, size, className)} {...rest} />;
}

export function ButtonLink({
  tone = "secondary",
  size = "md",
  className,
  ...rest
}: ComponentProps<typeof Link> & { tone?: ButtonTone; size?: ButtonSize }) {
  return <Link className={buttonClass(tone, size, className)} {...rest} />;
}

export const linkClass =
  "font-medium text-accent underline-offset-4 decoration-accent/40 hover:underline";

// -- Panels ------------------------------------------------------------------

export function Panel({
  className,
  children,
  as: Tag = "section",
  ...rest
}: { as?: "section" | "div" | "article"; className?: string; children: ReactNode } & Omit<
  ComponentProps<"section">,
  "className" | "children" | "ref"
>) {
  return (
    <Tag
      data-panel
      className={cx("min-w-0 rounded-lg border border-line bg-bg shadow-1", className)}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function PanelHeader({
  title,
  description,
  actions,
  icon,
  level = 2,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <header className="flex flex-col gap-3 border-b border-line px-4 py-3.5 sm:flex-row sm:items-start sm:justify-between sm:px-5">
      <div className="flex min-w-0 gap-2.5">
        {icon ? <span className="mt-0.5 text-text-3">{icon}</span> : null}
        <div className="min-w-0">
          <Heading className="text-[15px] font-semibold tracking-[-0.01em] text-text">{title}</Heading>
          {description ? (
            <p className="mt-0.5 max-w-prose text-[13px] leading-relaxed text-text-3">{description}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function PanelBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("px-4 py-4 sm:px-5", className)}>{children}</div>;
}

export function PanelFooter({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("border-t border-line bg-bg-soft px-4 py-3 text-[12px] text-text-3 sm:px-5", className)}>
      {children}
    </div>
  );
}

// -- Facts and values --------------------------------------------------------

/** A label over a value. Used inside a `<dl>`. */
export function Fact({
  label,
  children,
  hint,
  mono = false,
}: {
  label: ReactNode;
  children: ReactNode;
  hint?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-medium text-text-3">{label}</dt>
      <dd className={cx("mt-1 break-words text-[14px] text-text", mono && "font-mono text-[13px] tabular")}>
        {children}
      </dd>
      {hint ? <dd className="mt-1 text-[12px] leading-relaxed text-text-3">{hint}</dd> : null}
    </div>
  );
}

/**
 * The one way to say a value was not measured. Never a zero, a dash that
 * could be read as "none", or a blank.
 */
export function NotReported({ what }: { what?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[13px] text-text-3">
      <CircleSlash aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
      Not reported{what ? <span className="text-text-3">: {what}</span> : null}
    </span>
  );
}

/** A KPI tile. `value: null` renders NotReported with the reason. */
export function Stat({
  label,
  value,
  unit,
  detail,
  missing,
  icon,
}: {
  label: string;
  value: ReactNode | null;
  unit?: string;
  detail?: ReactNode;
  /** Why there is no value, shown when `value` is null. */
  missing?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-bg p-4 shadow-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] font-medium text-text-3">{label}</p>
        {icon ? <span className="text-text-3">{icon}</span> : null}
      </div>
      {value === null ? (
        <p className="mt-2.5 text-[13px] leading-snug text-text-3">{missing ?? "Not reported"}</p>
      ) : (
        <p className="mt-2 font-mono text-[26px] font-medium leading-none tracking-[-0.03em] text-text tabular">
          {value}
          {unit ? <span className="ml-1 text-[13px] font-normal tracking-normal text-text-3">{unit}</span> : null}
        </p>
      )}
      {detail ? <p className="mt-2 text-[12px] leading-relaxed text-text-3">{detail}</p> : null}
    </div>
  );
}

// -- States ------------------------------------------------------------------

export function EmptyState({
  title,
  children,
  action,
  icon,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-lg border border-line bg-bg-soft text-text-3">
        {icon ?? <Inbox aria-hidden="true" className="size-5" strokeWidth={1.5} />}
      </span>
      <p className="mt-4 text-[15px] font-semibold text-text">{title}</p>
      {children ? <div className="mt-1.5 max-w-md text-[13px] leading-relaxed text-text-3">{children}</div> : null}
      {action ? <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ title, detail }: { title: string; detail?: ReactNode }) {
  return (
    <div role="alert" className="flex gap-3 px-4 py-5 sm:px-5">
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-bad" strokeWidth={2} />
      <div className="min-w-0">
        <p className="text-[14px] font-semibold text-text">{title}</p>
        {detail ? <p className="mt-1 break-words text-[13px] leading-relaxed text-text-2">{detail}</p> : null}
      </div>
    </div>
  );
}

/** Inline feedback under a form or action. */
export function Notice({
  tone,
  children,
}: {
  tone: "ok" | "bad" | "warn" | "info";
  children: ReactNode;
}) {
  const style = {
    ok: "border-ok/25 bg-ok-soft text-ok",
    bad: "border-bad/25 bg-bad-soft text-bad",
    warn: "border-warn/25 bg-warn-soft text-warn",
    info: "border-accent-line bg-accent-soft text-accent",
  }[tone];
  return (
    <p
      role={tone === "bad" ? "alert" : "status"}
      className={cx("rounded-md border px-3 py-2 text-[13px] leading-relaxed", style)}
    >
      {children}
    </p>
  );
}

// -- Tables ------------------------------------------------------------------

/**
 * Wide tables scroll inside themselves; the page never scrolls sideways.
 * `relative` is load-bearing: an absolutely positioned descendant (a
 * screen-reader-only header label) is clipped only by a positioned scroll
 * container, and otherwise widened the whole page by 187 px at 390 px.
 */
export function TableScroll({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="relative min-w-0 overflow-x-auto" role={label ? "region" : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      {children}
    </div>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return <table className={cx("w-full border-collapse text-left text-[13px]", className)}>{children}</table>;
}

export function Th({ children, className, ...rest }: ComponentProps<"th">) {
  return (
    <th
      scope="col"
      className={cx(
        "whitespace-nowrap border-b border-line bg-bg-soft px-4 py-2.5 text-[12px] font-medium text-text-3 first:pl-4 sm:first:pl-5",
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
    <td className={cx("border-b border-line px-4 py-3 align-top text-text-2 first:pl-4 sm:first:pl-5", className)} {...rest}>
      {children}
    </td>
  );
}

// -- Layout ------------------------------------------------------------------

/** A titled section of a page body. */
export function Section({
  title,
  description,
  actions,
  children,
  id,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section aria-labelledby={id} className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id={id} className="text-[15px] font-semibold tracking-[-0.01em] text-text">
            {title}
          </h2>
          {description ? <p className="mt-0.5 text-[13px] text-text-3">{description}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line-strong bg-bg-soft px-1.5 py-0.5 font-mono text-[11px] text-text-2">
      {children}
    </kbd>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-bg-sunk px-1 py-0.5 font-mono text-[12px] text-text">{children}</code>;
}

// -- Loading -----------------------------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("bb-skeleton", className)} />;
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <Panel>
      <div role="status" aria-label="Loading" className="divide-y divide-line">
        <div className="flex gap-4 bg-bg-soft px-5 py-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-3.5">
            <Skeleton className="h-3.5 w-1/3" />
            <Skeleton className="h-3.5 w-16" />
            <Skeleton className="ml-auto h-3.5 w-20" />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function StatsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div role="status" aria-label="Loading" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,12rem),1fr))] gap-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-lg border border-line p-4">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-3 h-7 w-24" />
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-4">
      <StatsSkeleton />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-3 rounded-lg border border-line p-5">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
        <div className="space-y-3 rounded-lg border border-line p-5">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      </div>
    </div>
  );
}
