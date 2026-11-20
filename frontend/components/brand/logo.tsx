import Link from "next/link";

import { cx } from "@/components/ui/primitives";

/** Three signal bars in a square: a voice line under test. */
export function LogoMark({ className, inverted = false }: { className?: string; inverted?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cx("size-6 shrink-0", className)}>
      <rect width="24" height="24" rx="6" fill={inverted ? "#fafafa" : "#0a0a0a"} />
      <rect x="6" y="9" width="2.6" height="6" rx="1.3" fill={inverted ? "#0a0a0a" : "#fafafa"} />
      <rect x="10.7" y="5.5" width="2.6" height="13" rx="1.3" fill="#0a4bff" />
      <rect x="15.4" y="8" width="2.6" height="8" rx="1.3" fill={inverted ? "#0a0a0a" : "#fafafa"} />
    </svg>
  );
}

export function Logo({
  href = "/",
  inverted = false,
  className,
}: {
  href?: string;
  inverted?: boolean;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex items-center gap-2 rounded-md text-[16px] font-semibold tracking-[-0.02em]",
        inverted ? "text-night-text" : "text-text",
        className,
      )}
    >
      <LogoMark inverted={inverted} />
      <span>BhashaBench</span>
    </Link>
  );
}
