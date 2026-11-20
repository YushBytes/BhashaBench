import Link from "next/link";

import { Logo } from "@/components/brand/logo";
import { buttonClass } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <main id="main" className="flex min-h-dvh flex-col items-center justify-center px-6 text-center">
      <Logo />
      <p className="mt-10 font-mono text-[13px] text-text-3">404</p>
      <h1 className="mt-2 text-[28px] font-medium tracking-[-0.03em] text-text">Nothing here</h1>
      <p className="mt-2 max-w-sm text-[14px] leading-relaxed text-text-3">
        The page does not exist, or it belongs to a workspace you are not a member of. Both look the same on purpose.
      </p>
      <div className="mt-6 flex gap-2">
        <Link href="/app" className={buttonClass("primary", "md")}>
          Go to your workspace
        </Link>
        <Link href="/" className={buttonClass("secondary", "md")}>
          Home
        </Link>
      </div>
    </main>
  );
}
