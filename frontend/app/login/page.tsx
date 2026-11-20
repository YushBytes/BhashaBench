import { Suspense } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";
import { Skeleton } from "@/components/ui/primitives";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <AuthShell
      title="Sign in to BhashaBench"
      description="Your scenarios, runs and recordings are visible only to members of your workspace."
      aside={{
        title: "Pick up where your last run left off.",
        points: [
          "Runs that were in flight keep executing on the server and are followed live.",
          "Every turn keeps its audio, transcript and stage timings.",
          "Evaluations are appended, so earlier verdicts stay readable.",
        ],
      }}
    >
      <Suspense fallback={<Skeleton className="h-72 w-full" />}>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
