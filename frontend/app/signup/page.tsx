import Link from "next/link";
import { Suspense } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { SignupForm } from "@/components/auth/signup-form";
import { ErrorState, Notice, Skeleton, buttonClass } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api/client";

export const metadata = { title: "Create an account" };

export default function SignupPage() {
  return (
    <AuthShell
      title="Create your workspace"
      description="An account, a workspace you own and a Default project to put your first suite in."
      aside={{
        title: "What you can do in the first ten minutes.",
        points: [
          "Add a reference scenario from the shipped library, in Tamil, Hindi, English or another language.",
          "Run it offline to check the caller's logic before any audio moves.",
          "Point it at your bot over HTTP text or streaming voice and read back every turn.",
        ],
      }}
    >
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <SignupGate />
      </Suspense>
    </AuthShell>
  );
}

/** The form only where this deployment allows sign-up (`AUTH_ALLOW_SIGNUP`). */
async function SignupGate() {
  let enabled: boolean;
  try {
    enabled = (await api.authOptions({ cache: "no-store" })).signup_enabled;
  } catch (error) {
    return (
      <div className="rounded-lg border border-line">
        <ErrorState
          title="Sign-up could not be checked"
          detail={error instanceof ApiError ? error.message : "The API did not answer."}
        />
      </div>
    );
  }
  if (!enabled) {
    return (
      <div className="space-y-4">
        <Notice tone="info">
          This deployment does not allow self sign-up. Its operator creates accounts with the <code className="font-mono">bhashabench users create</code> command; a workspace owner or admin can then add you by email.
        </Notice>
        <Link href="/login" className={buttonClass("secondary", "lg", "w-full")}>
          Back to sign in
        </Link>
      </div>
    );
  }
  return <SignupForm />;
}
