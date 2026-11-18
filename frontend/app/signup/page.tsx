import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { SignupForm } from "@/components/domain/signup-form";
import { Wordmark } from "@/components/shell/wordmark";
import { api } from "@/lib/api/client";

export const metadata: Metadata = { title: "Create an account · BhashaBench" };

/** Reads the deployment's options at request time, so it is suspended. */
async function SignupBody() {
  let enabled = false;
  try {
    enabled = (await api.authOptions({ cache: "no-store" })).signup_enabled;
  } catch {
    enabled = false;
  }
  if (!enabled) {
    return (
      <p className="text-[14px] leading-relaxed text-text-muted">
        Sign-up is turned off on this server. An owner of a workspace adds you, or an operator
        creates your account with <code className="font-mono">bhashabench users create</code>.{" "}
        <Link href="/login" className="text-accent hover:underline">Back to sign in</Link>
      </p>
    );
  }
  return <SignupForm />;
}

export default function SignupPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg px-4 py-16">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-10 inline-flex min-h-11 items-center rounded-md">
          <Wordmark />
        </Link>
        <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text">Create an account</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-text-muted">
          You get your own workspace with a Default project. Nobody else can see it until you add them.
        </p>
        <div className="mt-8">
          <Suspense fallback={null}>
            <SignupBody />
          </Suspense>
        </div>
        <p className="mt-8 text-[13px] text-text-muted">
          Already have an account?{" "}
          <Link href="/login" className="text-accent hover:underline">Sign in</Link>
        </p>
      </div>
    </main>
  );
}
