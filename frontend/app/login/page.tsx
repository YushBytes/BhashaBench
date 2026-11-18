import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { LoginForm } from "@/components/domain/login-form";
import { Wordmark } from "@/components/shell/wordmark";

export const metadata: Metadata = { title: "Sign in · BhashaBench" };

/**
 * Sign-in. The sign-up link always leads somewhere true: /signup shows the
 * form where AUTH_ALLOW_SIGNUP is on, and otherwise says how accounts are
 * made on this server.
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
        <p className="mt-8 text-[13px] text-text-muted">
          No account?{" "}
          <Link href="/signup" className="text-accent hover:underline">Create one</Link>
          {" "}(where this server allows sign-up), or ask an owner of your workspace to add you.
        </p>
      </div>
    </main>
  );
}
