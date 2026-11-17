import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { LoginForm } from "@/components/domain/login-form";
import { Wordmark } from "@/components/shell/wordmark";

export const metadata: Metadata = { title: "Sign in · BhashaBench" };

/**
 * Sign-in. There is no sign-up link: accounts are created by an operator
 * (`bhashabench users create`) unless a deployment turns sign-up on, and a
 * link to a route that answers 403 would be a button that does not work.
 */
export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg px-4 py-16">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-10 inline-flex min-h-11 items-center rounded-md">
          <Wordmark />
        </Link>
        <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text">Sign in</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-text-muted">
          Your workspace holds your suites, runs and recordings. Nobody outside it can see them.
        </p>
        <div className="mt-8">
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </div>
        <p className="mt-8 text-[12px] leading-relaxed text-text-dim">
          No account? An owner of your workspace adds you; the first account on a server is
          created with <code className="font-mono">bhashabench users create</code>.
        </p>
      </div>
    </main>
  );
}
