import { cx } from "@/components/ui/primitives";

/**
 * The mark: four bars of a waveform, the second carrying the accent.
 *
 * Drawn rather than borrowed, and the only decorative vector in the product.
 * `aria-hidden` because the wordmark beside it already names the product;
 * announcing both would read the name twice.
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cx("shrink-0", className)}
    >
      <rect x="2" y="9" width="3" height="6" rx="1.5" fill="currentColor" opacity="0.45" />
      <rect x="7" y="4" width="3" height="16" rx="1.5" fill="currentColor" />
      <rect x="12" y="7" width="3" height="10" rx="1.5" fill="currentColor" opacity="0.72" />
      <rect x="17" y="10.5" width="3" height="3" rx="1.5" fill="currentColor" opacity="0.38" />
    </svg>
  );
}

export function Wordmark({
  className,
  subdued = false,
}: {
  className?: string;
  subdued?: boolean;
}) {
  return (
    <span className={cx("flex items-center gap-2", className)}>
      <Mark className={cx("size-5", subdued ? "text-text-dim" : "text-accent")} />
      <span className="text-[15px] font-semibold tracking-tight text-text">
        BhashaBench
      </span>
    </span>
  );
}
