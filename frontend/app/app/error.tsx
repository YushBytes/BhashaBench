"use client";

import Link from "next/link";
import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { Button, buttonClass } from "@/components/ui/primitives";

/**
 * A rendering failure inside the workspace. It says something went wrong on
 * our side and offers a retry; it never substitutes data for what failed.
 */
export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main" className="mx-auto flex w-full max-w-xl flex-1 flex-col items-start px-6 py-16">
      <AlertTriangle aria-hidden="true" className="size-6 text-bad" />
      <h1 className="mt-4 text-[22px] font-semibold tracking-[-0.02em] text-text">This page failed to render</h1>
      <p className="mt-2 text-[14px] leading-relaxed text-text-2">
        Something went wrong while building this page. Nothing was changed. Try again, and if it keeps failing, the reference below
        identifies the error in the server log.
      </p>
      {error.digest ? <p className="mt-3 font-mono text-[12px] text-text-3">Reference {error.digest}</p> : null}
      <div className="mt-6 flex gap-2">
        <Button tone="primary" onClick={reset}>
          Try again
        </Button>
        <Link href="/app" className={buttonClass("secondary", "md")}>
          Overview
        </Link>
      </div>
    </main>
  );
}
